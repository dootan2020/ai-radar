"""Durable data-only Git history; never force, reset, or write a code branch."""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from radar.edition_archive import archive_index, load_archive

BRANCH = "radar-editions"
REF = f"refs/heads/{BRANCH}"
DATA_PATH = re.compile(r"editions/(?:\d{4}-\d{2}-\d{2}|index)\.json\Z")


def git_environment(remote):
    """Pass the built-in token through process environment, never a URL or log."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    parsed = urlsplit(remote)
    if parsed.scheme in ("http", "https") and (parsed.username or parsed.password):
        raise ValueError("Remote URLs must not contain credentials")
    token = env.get("GITHUB_TOKEN")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if token and remote.startswith(server + "/"):
        authorization = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        count = int(env.get("GIT_CONFIG_COUNT", "0"))
        env[f"GIT_CONFIG_KEY_{count}"] = f"http.{server}/.extraheader"
        env[f"GIT_CONFIG_VALUE_{count}"] = "AUTHORIZATION: basic " + authorization
        env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def git(repo, remote, *args, allowed=(0,)):
    result = subprocess.run(["git", "-C", str(repo), *args], env=git_environment(remote),
                            capture_output=True, timeout=120)
    if result.returncode not in allowed:
        # Git diagnostics can contain credentials or server-controlled text.
        raise RuntimeError(f"Edition history Git {args[0]} failed (exit {result.returncode})")
    return result


def restore(remote, repo):
    """Fetch into a new temporary repo. Only ls-remote exit 2 means no branch."""
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)
    if any(repo.iterdir()):
        raise ValueError("History restore requires an empty temporary directory")
    git(repo, remote, "init", "--quiet")
    git(repo, remote, "config", "core.autocrlf", "false")
    result = git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, REF, allowed=(0, 2))
    if result.returncode == 2:
        return None
    lines = result.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or lines[0].split()[1:] != [REF]:
        raise ValueError("Unexpected edition branch lookup result")
    advertised = lines[0].split()[0]
    git(repo, remote, "fetch", "--quiet", "--no-tags", remote, REF)
    commit = git(repo, remote, "rev-parse", "FETCH_HEAD").stdout.decode().strip()
    if commit != advertised:
        raise ValueError("Edition branch changed during restore; retry the run")
    tree = git(repo, remote, "ls-tree", "-r", "-z", commit).stdout.decode("utf-8")
    paths = []
    for record in tree.split("\0"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        if not metadata.startswith("100644 blob ") or not DATA_PATH.fullmatch(path):
            raise ValueError("Edition branch contains an unexpected path or file type")
        paths.append(path)
    if "editions/index.json" not in paths:
        raise ValueError("Existing edition branch has no archive index")
    git(repo, remote, "checkout", "--quiet", "--detach", commit)
    files(repo / "editions")
    return commit


def files(directory):
    """Only plain JSON files belong to a candidate; no symlinks or subtrees."""
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Missing or invalid edition directory")
    result = {}
    for path in directory.iterdir():
        if path.is_symlink() or not path.is_file() or not DATA_PATH.fullmatch("editions/" + path.name):
            raise ValueError("Unexpected edition candidate file")
        result[path.name] = path.read_bytes()
    if "index.json" not in result:
        raise ValueError("Edition candidate has no index")
    archive = load_archive(directory)
    if json.loads(result["index.json"].decode("utf-8")) != archive_index(archive):
        raise ValueError("Edition history index does not describe the complete archive")
    return result


def persist(remote, candidate):
    """Append a prepared candidate with an optimistic base check and normal push."""
    candidate = Path(candidate)
    if candidate.is_symlink() or {p.name for p in candidate.iterdir()} != {"manifest.json", "editions"}:
        raise ValueError("Invalid edition candidate layout")
    manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "base_commit"}
            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["base_commit"] is not None
            and not re.fullmatch(r"[0-9a-f]{40,64}", str(manifest["base_commit"]))):
        raise ValueError("Invalid edition candidate manifest")
    desired = files(candidate / "editions")
    with tempfile.TemporaryDirectory(prefix="radar-history-") as temporary:
        repo = Path(temporary)
        base = restore(remote, repo)
        existing = files(repo / "editions") if base else {}
        if existing == desired:
            return False
        if base != manifest["base_commit"]:
            raise ValueError("Edition history advanced since preparation; collect again")
        for name, content in existing.items():
            if name != "index.json" and desired.get(name) != content:
                raise ValueError("Candidate changes or removes an immutable edition")
        destination = repo / "editions"
        destination.mkdir(exist_ok=True)
        for name in desired:
            shutil.copyfile(candidate / "editions" / name, destination / name)
        git(repo, remote, "add", "--", "editions")
        git(repo, remote, "-c", "user.name=github-actions[bot]", "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com", "commit", "--quiet",
            "-m", "feat: preserve daily editions")
        git(repo, remote, "push", "--quiet", remote, f"HEAD:{REF}")
        pushed = git(repo, remote, "rev-parse", "HEAD").stdout.decode().strip()
        observed = git(repo, remote, "ls-remote", "--exit-code", "--refs", remote, REF).stdout.decode().split()[0]
        if pushed != observed:
            raise RuntimeError("Edition push read-back differs from committed history")
    return True
