"""Halcyon repo recording, the checking half: `cay` fetches GitHub's own listing of a repo at one commit (API, no token, standard library) and
`compare` decides whether the stills quay-repo.mjs wrote show what GitHub holds. The comparison is pure (manifest + cay -> refusal or None) so the
tests need no network. Design: plans/reports/kongming-261120-0830-quay-repo-github.md sections 2 and 3.

    python video/halcyon/halcyon_quay.py cay     --repo owner/name [--branch b] [--open path ...] --out cay.json
    python video/halcyon/halcyon_quay.py compare --manifest <out>/<ref>/quay.json --cay cay.json
    python video/halcyon/halcyon_quay.py run     --repo owner/name [--branch b] [--open path ...] --ref name --out <folder>
Exit 0 = proved, 1 = refused (`cay: ...` or `quay: <address>: <kind>: <why>` and a `to fix:` line), 2 = bad arguments.
The walk through the pages is never changed to fit: a wrong path stops with the real children listed, never a substitute."""
import argparse
import base64
import json
import re
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = "https://api.github.com"
WEB = "https://github.com"
MAX_PAGES = 6                 # page loads per repo, quay-repo.mjs MAX_LOADS
API_BUDGET = 60               # unauthenticated calls per hour
MIN_INK_RATIO = 0.005         # under 0.5% ink = a blank picture
LUMINANCE_MIN = 0.5           # darker pages are refused, never converted
BANGKOK = timezone(timedelta(hours=7))
REPO_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$")


class Refusal(Exception):
    def __init__(self, step, kind, why, fix="", address=None):
        super().__init__(why)
        self.step, self.kind, self.why, self.fix, self.address = step, kind, why, fix, address

    def __str__(self):
        head = f"{self.step}: {self.address + ': ' if self.address else ''}{self.kind}: {self.why}"
        return head + (f"\nto fix: {self.fix}" if self.fix else "")


# ---------------------------------------------------------------- pure helpers
def norm(s):
    return re.sub(r"\s+", " ", s or "").strip()


def luminance(css_rgb):
    m = re.search(r"rgba?\(\s*(\d+)[ ,]+(\d+)[ ,]+(\d+)(?:[ ,/]+([\d.]+))?", css_rgb or "")
    if not m or (m.group(4) is not None and float(m.group(4)) == 0):
        return None
    r, g, b = (int(m.group(i)) for i in (1, 2, 3))
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def parent_of(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


def clean_open_path(p):
    if not isinstance(p, str) or not p or p.startswith("/") or "\\" in p or p.endswith("/"):
        raise Refusal("cay", "path", f"`{p}` is not a path from the repo root (no leading or trailing slash, no backslash)", "write it like packages/server")
    if any(seg in ("", ".", "..") for seg in p.split("/")):
        raise Refusal("cay", "path", f"`{p}` holds an empty, `.` or `..` part", "write it like packages/server")
    return p


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def bangkok(ts):
    return datetime.fromtimestamp(ts, BANGKOK).strftime("%H:%M on %d/%m/%Y (+07:00)")


# ---------------------------------------------------------------- cay: GitHub's own listing
def http_get(url, timeout=30):
    """Anonymous GET; never reads a token. Returns (status, lower-cased headers, body)."""
    req = urllib.request.Request(url, headers={"User-Agent": "halcyon-quay", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


class Api:
    def __init__(self, fetch):
        self.fetch, self.calls, self.remaining = fetch, 0, None

    def get(self, what, url):
        status, headers, body = self.fetch(url)
        self.calls += 1
        if "x-ratelimit-remaining" in headers:
            self.remaining = int(headers["x-ratelimit-remaining"])
        if status in (403, 429) and (headers.get("x-ratelimit-remaining") == "0" or status == 429):
            reset = headers.get("x-ratelimit-reset")
            when = f"; the limit resets at {bangkok(int(reset))}" if reset else ""
            raise Refusal("cay", "limit", f"GitHub's API limit ({API_BUDGET} calls an hour without a token) is used up while reading {what}{when}",
                          "wait for the reset, then run it again; no token is used")
        try:
            return status, json.loads(body.decode("utf-8")) if body else None
        except ValueError:
            raise Refusal("cay", "api", f"GitHub answered {what} with something that is not JSON (HTTP {status})", "try again later")


def children(tree, folder):
    """Direct children of `folder` ('' = root) from the recursive tree, with the collapsed address GitHub shows for a single-child folder chain."""
    by_parent = {}
    for e in tree:
        by_parent.setdefault(parent_of(e["path"]), []).append(e)
    kinds = {e["path"]: e["type"] for e in tree}
    out = []
    for e in sorted(by_parent.get(folder, []), key=lambda e: e["path"]):
        kind = {"tree": "tree", "blob": "blob"}.get(e["type"], e["type"])
        chain = e["path"]
        while kinds.get(chain) == "tree" and len(by_parent.get(chain, [])) == 1 and by_parent[chain][0]["type"] == "tree":
            chain = by_parent[chain][0]["path"]
        out.append({"name": e["path"].rsplit("/", 1)[-1], "path": e["path"], "kind": kind, "chain_to": chain})
    return out


def cay(repo, open_paths=(), branch=None, fetch=http_get, now=None):
    if not REPO_RE.match(repo or ""):
        raise Refusal("cay", "repo", f"`{repo}` is not owner/name", "write the repo like backnotprop/plannotator")
    paths, chain_flag = [], {}
    for p in open_paths:
        chain = False
        if isinstance(p, dict):                    # {"path": "a/b/c", "chain": true}: GitHub shows the single-child folder chain as one row
            chain, p = bool(p.get("chain")), p.get("path")
        p = clean_open_path(p)
        if p in paths:
            raise Refusal("cay", "path", f"`{p}` is listed twice", "list each page once")
        paths.append(p)
        chain_flag[p] = chain
    if len(paths) + 1 > MAX_PAGES:
        raise Refusal("cay", "rate-limit", f"{len(paths) + 1} pages are needed (the home page and {len(paths)} more) and a repo may be loaded {MAX_PAGES} times at most",
                      f"open at most {MAX_PAGES - 1} paths")
    api = Api(fetch)
    q = urllib.parse.quote
    status, meta = api.get(f"the repo {repo}", f"{API}/repos/{repo}")
    if status == 404:
        raise Refusal("cay", "repo", f"{repo} does not exist or is private (GitHub answers 404 without a sign-in)", "use a public repo; check the spelling of owner/name")
    if status != 200 or not meta:
        raise Refusal("cay", "api", f"GitHub answered HTTP {status} for {repo}", "try again later")
    if meta.get("full_name", repo).lower() != repo.lower():
        raise Refusal("cay", "renamed", f"{repo} is now {meta['full_name']}", f"use {meta['full_name']}")
    if meta.get("private"):
        raise Refusal("cay", "repo", f"{repo} is private", "use a public repo")
    branch = branch or meta.get("default_branch")
    status, commit = api.get(f"the branch {branch}", f"{API}/repos/{repo}/commits/{q(branch, safe='')}")
    if status != 200 or not commit or "sha" not in commit:
        raise Refusal("cay", "branch", f"{repo} has no branch `{branch}` (HTTP {status})", "name an existing branch or leave it out for the default branch")
    sha = commit["sha"]
    status, tree = api.get(f"the file tree of {repo}", f"{API}/repos/{repo}/git/trees/{sha}?recursive=1")
    if status != 200 or not tree:
        raise Refusal("cay", "api", f"GitHub answered HTTP {status} for the file tree of {repo} at {sha[:7]}", "try again later")
    if tree.get("truncated"):
        raise Refusal("cay", "listing", f"{repo} has too many files for one listing (GitHub cut the tree at {sha[:7]})", "pick a smaller repo; no part of it is guessed")
    entries = tree["tree"]
    kinds = {e["path"]: e["type"] for e in entries}

    pages = [{"path": "", "kind": "home"}]
    for p in paths:
        if p not in kinds:
            near = p
            while near and near not in kinds:
                near = parent_of(near)
            if near and kinds.get(near) == "blob":
                raise Refusal("cay", "parent", f"`{p}` is not in {repo} at `{sha[:7]}`: `{near}` is a file, not a folder", f"open `{near}` as a file and nothing below it")
            held = [c["name"] for c in children(entries, near)]
            raise Refusal("cay", "path", f"`{p}` is not in {repo} at `{sha[:7]}`; `{near or '/'}` holds: {', '.join(held[:40])}{' ...' if len(held) > 40 else ''}",
                          f"pick one of those (`{(near + '/') if near else ''}<name>`)")
        opened = [x["path"] for x in pages]
        par = parent_of(p)
        if kinds[p] == "commit":
            raise Refusal("cay", "path", f"`{p}` is a submodule, which links to another repo", "open a folder or file of this repo")
        entry = {"path": p, "kind": "tree" if kinds[p] == "tree" else "blob"}
        if chain_flag[p]:
            # every folder skipped between the row and `p` must hold exactly one thing: the next folder of the chain
            below = p
            while par and par not in opened:
                held = [c["name"] for c in children(entries, par)]
                if kinds.get(par) != "tree" or len(held) != 1 or kinds.get(below) != "tree":
                    raise Refusal("cay", "chain", f"`{p}` is not a single-folder chain: `{par}` holds {len(held)} entries ({', '.join(held[:12])})",
                                  f"open `{par}` as its own page, or drop \"chain\"")
                below, par = par, parent_of(par)
            entry["chain"] = True
            entry["chain_parent"] = par
        elif par and par not in opened:
            raise Refusal("cay", "parent", f"the parent of `{p}` (`{par}`) is not opened before it", f"list `{par}` earlier in the same open list, or write {{'path': '{p}', 'chain': true}} if GitHub shows it collapsed")
        pages.append(entry)

    needed = len([x for x in pages if x["kind"] == "blob"])
    if api.remaining is not None and api.remaining < needed:
        raise Refusal("cay", "limit", f"{needed} more API calls are needed and only {api.remaining} are left this hour", "wait for the reset; no token is used")
    listings = {x["path"]: children(entries, x["path"]) for x in pages if x["kind"] in ("home", "tree")}
    files = {}
    for x in pages:
        if x["kind"] != "blob":
            continue
        status, doc = api.get(f"the file {x['path']}", f"{API}/repos/{repo}/contents/{q(x['path'])}?ref={sha}")
        if status != 200 or not isinstance(doc, dict):
            raise Refusal("cay", "api", f"GitHub answered HTTP {status} for the file `{x['path']}`", "try again later")
        raw = base64.b64decode(doc.get("content", "") or "") if doc.get("encoding") == "base64" else b""
        if doc.get("size", 0) and not raw:
            files[x["path"]] = {"state": "too-large", "first_line": None, "index": None}
            continue
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            files[x["path"]] = {"state": "binary", "first_line": None, "index": None}
            continue
        lines = text.splitlines()
        idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        files[x["path"]] = {"state": "empty" if idx is None else "text", "first_line": None if idx is None else lines[idx], "index": idx}
    stamp = (now or datetime.now(BANGKOK)).strftime("%Y-%m-%dT%H:%M:%S+07:00")
    return {"version": 1, "repo": repo, "branch": branch, "commit": sha, "fetched": stamp, "open": paths, "pages": pages, "listings": listings, "files": files,
            "api_calls": api.calls, "api_remaining": api.remaining}


# ---------------------------------------------------------------- compare: what is on screen vs what GitHub holds
def expected_path(repo, branch, page):
    if page["kind"] == "home":
        return f"/{repo}"
    return f"/{repo}/{'tree' if page['kind'] == 'tree' else 'blob'}/{branch}/{page['path']}"


def check_page(manifest, cay_doc, mp, cp, pic_dir=None):
    """Refuse (raise) on the first thing that makes one page untrustworthy. mp = manifest page, cp = the cay page it must match."""
    repo, branch = cay_doc["repo"], cay_doc["branch"]
    addr = mp.get("requested") or expected_path(repo, branch, cp)

    def refuse(kind, why, fix=""):
        raise Refusal("quay", kind, why, fix, addr)

    if mp.get("status") != 200:
        refuse("status", f"HTTP {mp.get('status')} (200 needed)", "check the address; a missing page is never replaced")
    final = urllib.parse.urlsplit(mp.get("final") or "")
    fpath = urllib.parse.unquote(final.path).rstrip("/")
    owner_name = "/".join(fpath.split("/")[1:3])
    if owner_name.lower() != repo.lower():
        refuse("renamed", f"the page ended at {fpath or '(nothing)'}, so the repo {repo} has moved to {owner_name}", f"use {owner_name} as the repo")
    lum = luminance(mp.get("background"))
    if lum is None or lum < LUMINANCE_MIN:
        refuse("theme", f"the page background is {mp.get('background')}; only the light theme is shown, never converted", "")
    want = expected_path(repo, branch, cp)
    got = fpath if cp["kind"] != "home" else "/" + owner_name
    if (got.lower() if cp["kind"] == "home" else got) != (want.lower() if cp["kind"] == "home" else want) or mp.get("type") != cp["kind"]:
        refuse("address", f"asked for {want} and the page ended at {fpath or '(nothing)'} (type {mp.get('type')}, wanted {cp['kind']})", "the branch or path was moved; run the listing again")
    title = (mp.get("title") or "").lower()
    last = cp["path"].rsplit("/", 1)[-1].lower() if cp["path"] else ""
    if repo.split("/")[1].lower() not in title and not (last and last in title):
        refuse("address", f"the page title \"{mp.get('title')}\" names neither the repo nor `{last or repo}`", "")
    # the picture itself
    w, h = cay_doc_scale(manifest)
    expect_px = [w, mp.get("css_height", 0) * manifest["scale"]]
    px = mp.get("picture_px")
    if pic_dir is not None:
        f = Path(pic_dir) / (mp.get("picture") or "")
        sz = png_size(f) if f.exists() else None
        if sz is None:
            refuse("blank", f"the picture {mp.get('picture')} is missing or is not a PNG", "capture the page again")
        px = list(sz)
    if px != expect_px:
        refuse("blank", f"the picture is {px}, expected {expect_px} (width x css height x scale)", "capture the page again")
    if (mp.get("ink_ratio") or 0) < MIN_INK_RATIO:
        refuse("blank", f"the picture holds {100 * (mp.get('ink_ratio') or 0):.2f}% ink, under {100 * MIN_INK_RATIO:.1f}%: a blank page", "capture the page again")
    if cp["kind"] in ("home", "tree"):
        check_listing(cay_doc, mp, cp, addr)
    if cp["kind"] == "blob":
        check_file(cay_doc, mp, cp, addr)


def cay_doc_scale(manifest):
    return manifest["viewport"]["width"] * manifest["scale"], manifest["viewport"]["height"] * manifest["scale"]


def check_listing(cay_doc, mp, cp, addr):
    def refuse(kind, why, fix=""):
        raise Refusal("quay", kind, why, fix, addr)

    expected = [c for c in cay_doc["listings"][cp["path"]] if c["kind"] in ("tree", "blob")]   # a submodule row links elsewhere and is not an address row
    by_screen = {}
    for c in expected:
        by_screen[c["path"]] = c
        by_screen[c["chain_to"]] = c
    seen = set()
    for r in mp.get("rows", []):
        c = by_screen.get(r["path"])
        if c is None:
            refuse("listing", f"the page shows a row `{r['path']}` that GitHub's own listing of `{cp['path'] or '/'}` at {cay_doc['commit'][:7]} does not hold", "a push may have landed; run it again")
        seen.add(c["path"])
    missing = [c["path"] for c in expected if c["path"] not in seen]
    if missing and not (mp.get("truncated") and not mp.get("expanded")):
        refuse("listing", f"GitHub lists {len(expected)} entries in `{cp['path'] or '/'}` and the page shows {len(seen)}; missing: {', '.join(missing[:8])}{' ...' if len(missing) > 8 else ''}",
               "a push may have landed, or the page was cut; run it again")
    if mp.get("truncated") and not mp.get("expanded") and missing:
        refuse("listing", "the page cuts the list behind \"View all files\" and it was not expanded", "run it again")
    nxt = [p for p in cay_doc["pages"] if p["path"] and p.get("chain_parent", parent_of(p["path"])) == cp["path"]]
    rows = {r["path"]: r for r in mp.get("rows", [])}
    for p in nxt:
        row = rows.get(p["path"])
        if row is None:
            deeper = [k for k in rows if k.startswith(p["path"] + "/")]
            if p.get("chain"):
                refuse("row", f"the page has no row whose address is the full path `{p['path']}`, which the video opens next as a collapsed chain", "")
            if deeper:
                refuse("row", f"GitHub shows `{p['path']}` collapsed into the row `{deeper[0]}` (a folder with one folder in it)", f"open `{deeper[0]}` instead")
            refuse("row", f"the page has no row for `{p['path']}`, which the video opens next", "")
        x, y, w, h = row["rect"]
        if y < 0 or y + h > mp["css_height"]:
            refuse("row", f"the row for `{p['path']}` lies at y {y}..{y + h}, below the {mp['css_height']} css px of the picture", "open the path from a folder page, not the long home page")


def check_file(cay_doc, mp, cp, addr):
    def refuse(kind, why, fix=""):
        raise Refusal("quay", kind, why, fix, addr)

    info = (mp.get("file") or {})
    if info.get("kind") != "code":
        return          # a rendered markdown file or a preview is proved by address and title only
    want = cay_doc["files"].get(cp["path"])
    if want is None or want["state"] in ("too-large", "binary"):
        refuse("file", f"`{cp['path']}` cannot be compared line by line ({want['state'] if want else 'unknown'})", "open a text file under 1 MB")
    lines = info.get("code_lines") or []
    if want["state"] == "empty":
        if any(norm(x) for x in lines):
            refuse("file", f"`{cp['path']}` is empty at {cay_doc['commit'][:7]} but the page shows code", "")
        return
    i = want["index"]
    if len(lines) <= i or norm(lines[i]) != norm(want["first_line"]) or any(norm(x) for x in lines[:i]):
        shown = norm(lines[i]) if len(lines) > i else "(no line)"
        refuse("file", f"the first line of `{cp['path']}` is \"{norm(want['first_line'])[:80]}\" on GitHub and \"{shown[:80]}\" on screen", "capture the page again")


def compare(manifest, cay_doc, pic_dir=None):
    """Raise Refusal unless every page of the manifest is the page of `cay_doc` and shows what GitHub holds."""
    if manifest.get("repo", "").lower() != cay_doc["repo"].lower() or manifest.get("commit") != cay_doc["commit"] or manifest.get("branch") != cay_doc["branch"]:
        raise Refusal("quay", "address", f"the stills are of {manifest.get('repo')}@{manifest.get('branch')} {str(manifest.get('commit'))[:7]}, the listing is of {cay_doc['repo']}@{cay_doc['branch']} {cay_doc['commit'][:7]}",
                      "run cay and quay together")
    mpages = manifest.get("pages", [])
    if [p["path"] for p in mpages] != [p["path"] for p in cay_doc["pages"]]:
        raise Refusal("quay", "address", f"the stills hold the pages {[p['path'] for p in mpages]} and the walk needs {[p['path'] for p in cay_doc['pages']]}", "capture again")
    for mp, cp in zip(mpages, cay_doc["pages"]):
        check_page(manifest, cay_doc, mp, cp, pic_dir)
    return None


# ---------------------------------------------------------------- commands
def run_quay(repo, open_paths, ref, out, branch=None, base=WEB, fetch=http_get, node="node", timeout=45, say=print):
    """cay, then quay-repo.mjs, then the comparison; a listing mismatch is retried once from a fresh cay when the repo moved in between."""
    out = Path(out)
    work = out / ref
    work.mkdir(parents=True, exist_ok=True)
    for attempt in (1, 2):
        doc = cay(repo, open_paths, branch, fetch)
        cay_file = work / "cay.json"
        cay_file.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
        cmd = [node, str(HERE / "quay-repo.mjs"), "--cay", str(cay_file), "--ref", ref, "--out", str(out), "--base", base, "--timeout", str(timeout)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if r.returncode != 0:
            msg = (r.stderr.strip().splitlines() or ["quay: the recorder failed"])[-1]
            m = re.match(r"quay: (\S+): (\S+): (.*?)(?:; nothing written)?$", msg)
            if r.returncode == 1 and m:
                raise Refusal("quay", m.group(2), m.group(3), "", m.group(1))
            raise Refusal("quay", "error", msg or r.stdout.strip()[-300:], "")
        manifest = json.loads((work / "quay.json").read_text(encoding="utf-8"))
        try:
            compare(manifest, doc, work)
            say(f"quay: {repo}@{doc['commit'][:7]}: {len(manifest['pages'])} pages match GitHub's own listing ({work})")
            return manifest, doc
        except Refusal as e:
            if e.kind == "listing" and attempt == 1:
                fresh = cay(repo, open_paths, branch, fetch)
                if fresh["commit"] != doc["commit"]:
                    say(f"quay: a push landed between the listing and the pages ({doc['commit'][:7]} -> {fresh['commit'][:7]}); capturing once more")
                    shutil.rmtree(work, ignore_errors=True)
                    work.mkdir(parents=True, exist_ok=True)
                    continue
            raise


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("cay", "run"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--branch")
        p.add_argument("--open", action="append", default=[], help="a path from the repo root, in the order shown; repeat; write a/b/c#chain when GitHub shows a single-folder chain as one row")
        if name == "cay":
            p.add_argument("--out", required=True)
        else:
            p.add_argument("--ref", required=True)
            p.add_argument("--out", required=True)
            p.add_argument("--base", default=WEB)
    c = sub.add_parser("compare")
    c.add_argument("--manifest", required=True)
    c.add_argument("--cay", required=True)
    a = ap.parse_args(argv)
    if getattr(a, "open", None):
        a.open = [{"path": o[:-6], "chain": True} if o.endswith("#chain") else o for o in a.open]
    try:
        if a.cmd == "cay":
            doc = cay(a.repo, a.open, a.branch)
            Path(a.out).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
            print(f"cay: {a.repo}@{doc['commit'][:7]} ({doc['branch']}): {len(doc['pages'])} pages, {doc['api_calls']} API calls -> {a.out}")
        elif a.cmd == "compare":
            mf = Path(a.manifest)
            compare(json.loads(mf.read_text(encoding="utf-8")), json.loads(Path(a.cay).read_text(encoding="utf-8")), mf.parent)
            print("quay: the stills match GitHub's listing")
        else:
            if not re.match(r"^[\w.-]+$", a.ref):
                print("quay: --ref may hold letters, digits, dot, dash and underscore only", file=sys.stderr)
                return 2
            run_quay(a.repo, a.open, a.ref, a.out, a.branch, a.base)
    except Refusal as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
