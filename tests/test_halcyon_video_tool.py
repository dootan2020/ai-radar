"""Halcyon video builder (video/halcyon): checks that need no GPU, no numpy and no ffmpeg.

The builder itself is proven by rebuilding a published video (see video/halcyon/README.md); these tests cover the spec loader's refusals,
that the committed tool carries no machine-specific path, and that every font and brand mark the drawing code names is in the repository.
"""
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "video" / "halcyon"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


halcyon_spec = load_module("halcyon_spec", TOOL / "halcyon_spec.py")


def minimal_spec():
    return {
        "name": "t", "duration": 2.0, "voice": "v.wav", "timing": "t.json",
        "captions": ["a"], "tiktok_caption": ["x", "y"],
        "out": {"clean": "c.mp4", "tiktok": "t.mp4"}, "beats": [],
    }


class SpecLoaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / "v.wav").write_bytes(b"")
        (self.dir / "t.json").write_text(json.dumps({"words_whisper_medium": [{"w": "a", "s": 0.0, "e": 0.1}]}), encoding="utf-8")

    def write(self, spec):
        path = self.dir / "video.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_valid_spec_resolves_paths_next_to_the_spec(self):
        s = halcyon_spec.load_spec(self.write(minimal_spec()), 30, "A")
        self.assertEqual(s["voice"], (self.dir / "v.wav").resolve())
        self.assertEqual(s["out_clean"], self.dir.resolve() / "c.mp4")
        self.assertEqual(s["total"], 60)
        self.assertEqual(s["layout"], "A")
        self.assertEqual(len(s["words"]), 1)

    def test_every_required_top_level_field_is_refused_when_missing(self):
        for field in ("name", "duration", "voice", "timing", "captions", "tiktok_caption", "out", "beats"):
            spec = minimal_spec()
            del spec[field]
            with self.subTest(field=field), self.assertRaises(SystemExit) as cm:
                halcyon_spec.load_spec(self.write(spec), 30, "A")
            self.assertIn(f"spec.{field} is missing", str(cm.exception))

    def test_missing_out_field_names_the_field(self):
        spec = minimal_spec()
        del spec["out"]["tiktok"]
        with self.assertRaises(SystemExit) as cm:
            halcyon_spec.load_spec(self.write(spec), 30, "A")
        self.assertIn("spec.out.tiktok is missing", str(cm.exception))

    def test_missing_voice_file_is_refused(self):
        (self.dir / "v.wav").unlink()
        with self.assertRaises(SystemExit) as cm:
            halcyon_spec.load_spec(self.write(minimal_spec()), 30, "A")
        self.assertIn("does not exist", str(cm.exception))

    def test_timing_file_without_the_word_list_is_refused(self):
        (self.dir / "t.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as cm:
            halcyon_spec.load_spec(self.write(minimal_spec()), 30, "A")
        self.assertIn("words_whisper_medium", str(cm.exception))


class PortableToolTest(unittest.TestCase):
    def test_no_machine_specific_path_in_the_tool(self):
        pattern = re.compile(r"[A-Za-z]:[\\/]+(Users|Windows)|[A-Za-z]:\\\\|\bD:[\\/]|firstmate|worktree|/home/|AppData", re.I)
        allowed = "C:/Windows"  # the documented fallback of %SystemRoot% for the Segoe UI phone previews
        files = [p for p in TOOL.rglob("*") if p.is_file() and p.suffix in (".py", ".ps1", ".md")]
        self.assertTrue(files)
        for path in files:
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                found = pattern.search(line.replace(allowed, ""))
                self.assertIsNone(found, f"{path.name}:{number}: {line.strip()}")

    def test_fonts_and_marks_named_by_the_drawing_code_are_in_the_repository(self):
        source = (TOOL / "ve_halcyon.py").read_text(encoding="utf-8")
        font_dirs = [TOOL / "fonts", ROOT / "brand" / "fonts"]
        mark_dirs = [ROOT / "brand" / "logo" / "coral-tile" / "logos"]
        fonts = set(re.findall(r"'((?:BarlowCondensed|BeVietnamPro)-[A-Za-z]+\.ttf)'", source))
        marks = set(re.findall(r"raster\('([\w.-]+\.svg)'", source))
        self.assertTrue(fonts and marks)
        for name in fonts:
            self.assertTrue(any((d / name).is_file() for d in font_dirs), name)
        for name in marks:
            self.assertTrue(any((d / name).is_file() for d in mark_dirs), name)

    def test_committed_binaries_stay_small_and_licensed(self):
        for path in TOOL.rglob("*.ttf"):
            self.assertLess(path.stat().st_size, 200_000, path.name)
            family = path.name.split("-")[0]
            self.assertTrue(list((TOOL / "fonts").glob(f"OFL-{family}.txt")), f"licence text for {path.name}")
        self.assertEqual([p.name for p in TOOL.rglob("*") if p.suffix in (".png", ".jpg", ".mp3", ".wav", ".mp4", ".webm")], [])


if __name__ == "__main__":
    unittest.main()
