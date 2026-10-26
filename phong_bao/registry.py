"""Declarative capability registry and safe provider selection."""

from __future__ import annotations

import tomllib
from pathlib import Path

CAPABILITIES = {"tim-kiem", "doc-bai", "bien-tap", "kiem-chung", "tao-anh", "dung-video", "giong-doc"}
KINDS = {"local-command": 0, "subscription-boat": 1, "mcp-plugin": 1, "paid-api": 2}
COSTS = {"free", "subscription", "paid"}
DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "phong-bao" / "cong-cu"


def load_registry(directory=DEFAULT_REGISTRY):
    tools = []
    for path in sorted(Path(directory).glob("*.toml")):
        with path.open("rb") as handle:
            tool = tomllib.load(handle)
        required = {"id", "capabilities", "kind", "cost_class", "priority", "monthly_cap_usd", "detect"}
        if required - tool.keys() or tool["kind"] not in KINDS or tool["cost_class"] not in COSTS:
            raise ValueError(f"invalid tool profile: {path.name}")
        if not isinstance(tool["capabilities"], list) or not tool["capabilities"] or set(tool["capabilities"]) - CAPABILITIES:
            raise ValueError(f"invalid capabilities: {path.name}")
        if not isinstance(tool["priority"], int) or not isinstance(tool["monthly_cap_usd"], (int, float)) or tool["monthly_cap_usd"] < 0:
            raise ValueError(f"invalid cost settings: {path.name}")
        if tool["kind"] == "paid-api" and not tool["monthly_cap_usd"]:
            raise ValueError(f"paid API requires a spending cap: {path.name}")
        if tool["kind"] != "paid-api" and tool["monthly_cap_usd"]:
            raise ValueError(f"non-API tool cannot spend: {path.name}")
        if not isinstance(tool["detect"], dict) or not set(tool["detect"]) <= {"command", "mcp_server", "env_key", "file"} or len(tool["detect"]) != 1:
            raise ValueError(f"invalid detection rule: {path.name}")
        tool["file"] = path.name
        tools.append(tool)
    ids = [tool["id"] for tool in tools]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate tool id")
    return tools


def available(tool, discovery):
    method, name = next(iter(tool["detect"].items()))
    if name not in discovery.get({"command": "commands", "mcp_server": "mcp_servers", "env_key": "key_names", "file": "files"}[method], []):
        return False
    fuel = discovery.get("fuel")
    boat = tool.get("boat")
    if boat and isinstance(fuel, str):
        fuel_name = "gemini" if boat == "agy" else boat
        for line in fuel.splitlines():
            if line.strip().casefold().startswith(fuel_name + " ") or line.strip().casefold().startswith(fuel_name + ":"):
                if any(marker in line.upper() for marker in ("CẠN", "CHẠM TRẦN", "CHẠM DỰ TRỮ")):
                    return False
    return True


def providers(capability, tools, discovery, *, exclude=(), boat_exclude=()):
    selected = [tool for tool in tools if capability in tool["capabilities"] and available(tool, discovery)
                and tool["id"] not in exclude and tool.get("boat") not in boat_exclude
                and tool.get("runner") != "disabled-until-budget-adapter"]
    return sorted(selected, key=lambda tool: (KINDS[tool["kind"]], tool["priority"], tool["id"]))
