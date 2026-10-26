"""Read capability presence, never secret contents or unknown tools."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .registry import CAPABILITIES, available, fuel_status, load_registry, providers
from .runner import AdmissionError

FUEL_SCRIPT = Path("C:/Users/Admin/agent-config/tools/hai-thuyen.py")
COMMANDS_TO_CHECK = {"codex", "agy", "claude", "npx", "remotion", "ffmpeg", "python"}
KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]*(?:_KEY|_TOKEN|_SECRET)$")


def _call(argv, timeout=15):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def _mcp_names(output):
    names = []
    for line in output.splitlines():
        match = re.match(r"^\s*([\w.-]+):\s+", line)
        if match:
            names.append(match[1].casefold())
    return sorted(set(names))


def discover_raw(*, fixture=None):
    if fixture is not None:
        return {key: fixture.get(key, []) for key in ("commands", "mcp_servers", "key_names", "files", "fuel")}
    declared = load_registry()
    declared_commands = {tool["detect"]["command"] for tool in declared if "command" in tool["detect"]}
    commands = sorted(name for name in COMMANDS_TO_CHECK | declared_commands if shutil.which(name))
    files = sorted(tool["detect"]["file"] for tool in declared
                   if "file" in tool["detect"] and Path(tool["detect"]["file"]).is_file())
    keys = {name for name in os.environ if KEY_NAME.fullmatch(name)}
    vault = Path.home() / ".firstmate" / "secrets"
    if vault.is_dir():
        keys.update(path.stem.upper() for path in vault.iterdir() if path.is_file() and KEY_NAME.fullmatch(path.stem.upper()))
    mcp = []
    if "claude" in commands:
        result = _call([shutil.which("claude"), "mcp", "list"])
        if result:
            if result.returncode and re.search(r"sign\s*in|log\s*in|billing|payment|purchase|upgrade your plan|different account|different model",
                                               result.stdout + result.stderr, re.I):
                raise AdmissionError("Claude MCP discovery requested account, payment, or model change")
            if result.returncode == 0:
                mcp = _mcp_names(result.stdout)
    fuel = "unavailable"
    if FUEL_SCRIPT.is_file():
        result = _call([sys.executable, str(FUEL_SCRIPT), "trang-thai", "--do-gemini"], timeout=90)
        if result and re.search(r"sign\s*in|log\s*in|billing|payment|purchase|upgrade your plan|different account|different model",
                                result.stdout + result.stderr, re.I):
            raise AdmissionError("Gemini fuel discovery requested account, payment, or model change")
        if result and result.returncode == 0:
            # Keep only fuel lines; the script also prints unrelated job titles.
            fuel = "\n".join(line for line in result.stdout.splitlines()
                             if line.strip().casefold().startswith(("codex ", "codex :", "gemini ", "claude ")))
    return {"commands": commands, "mcp_servers": mcp, "key_names": sorted(keys), "files": files, "fuel": fuel}


def report(raw, tools=None):
    tools = tools if tools is not None else load_registry()
    raw = {key: raw.get(key, []) for key in ("commands", "mcp_servers", "key_names", "files", "fuel")}
    configured = {"commands": set(), "mcp_servers": set(), "key_names": set(), "files": set()}
    for tool in tools:
        method, name = next(iter(tool["detect"].items()))
        configured[{"command": "commands", "mcp_server": "mcp_servers", "env_key": "key_names", "file": "files"}[method]].add(name)
    return {
        "detected": raw,
        "tools": [{"id": tool["id"], "available": available(tool, raw), "kind": tool["kind"],
                   **({"fuel_status": fuel_status(tool, raw)} if tool.get("boat") else {}),
                   **({"state": "session_only"} if tool["id"] == "canva-mcp"
                      and "canva" not in raw["mcp_servers"] else {}),
                   **({"required_context": "Claude session"} if tool["id"] == "canva-mcp"
                      and "canva" not in raw["mcp_servers"] else {})} for tool in tools],
        "selected": {cap: [tool["id"] for tool in providers(cap, tools, raw)] for cap in sorted(CAPABILITIES)},
        "found_not_configured": {key: sorted(set(raw[key]) - configured[key]) for key in configured},
    }
