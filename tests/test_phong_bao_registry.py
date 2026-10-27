import json
import unittest
from pathlib import Path

from phong_bao.registry import load_registry, providers

FIXTURES = Path(__file__).parent / "fixtures" / "phong-bao"
DESK_CAPABILITY = {"reporter": "doc-bai", "editor": "bien-tap", "checker": "kiem-chung", "writer": "bien-tap"}


class DeskPriorityTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_registry()
        self.discovery = json.loads((FIXTURES / "discovery.json").read_text(encoding="utf-8"))
        self.discovery["fuel"] = "  codex        : còn\n  gemini       : còn"

    def batch_order(self, capability, desk):
        return [tool["id"] for tool in providers(capability, self.tools, self.discovery, desk=desk)
                if tool.get("runner") == "batch-cli"]

    def test_every_desk_prefers_agy_and_keeps_codex_as_fallback(self):
        for desk, capability in DESK_CAPABILITY.items():
            order = self.batch_order(capability, desk)
            self.assertEqual(order[:2], ["agy", "codex"], desk)

    def test_codex_alone_serves_a_desk_when_agy_is_dry(self):
        self.discovery["fuel"] = "  codex        : còn\n  gemini       : CẠN"
        for desk, capability in DESK_CAPABILITY.items():
            self.assertEqual(self.batch_order(capability, desk), ["codex"], desk)


if __name__ == "__main__":
    unittest.main()
