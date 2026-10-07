import json
import os
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

try:
    import numpy  # noqa: F401

    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

REPO_ROOT = Path(__file__).resolve().parent.parent


class VideoOmniVoiceResolutionTestCase(unittest.TestCase):
    def setUp(self):
        self.wrapper_path = REPO_ROOT / "video" / "scripts" / "omnivoice_tts.py"
        self.fix_script_path = REPO_ROOT / "video" / "scripts" / "fix_omnivoice.py"

    def test_vendored_scripts_exist_and_not_in_gitignored_dirs(self):
        self.assertTrue(
            self.wrapper_path.is_file(),
            f"Vendored OmniVoice wrapper missing: {self.wrapper_path}",
        )
        self.assertTrue(
            self.fix_script_path.is_file(),
            f"Vendored Fix OmniVoice script missing: {self.fix_script_path}",
        )
        norm_wrapper = str(self.wrapper_path).replace("\\", "/").lower()
        norm_fix = str(self.fix_script_path).replace("\\", "/").lower()
        self.assertNotIn("plans", norm_wrapper)
        self.assertNotIn("tham-chieu", norm_wrapper)
        self.assertNotIn("plans", norm_fix)
        self.assertNotIn("tham-chieu", norm_fix)

    def test_omnivoice_tts_resolves_sibling_fix_script(self):
        scripts_dir = str(REPO_ROOT / "video" / "scripts")
        sys.path.insert(0, scripts_dir)
        try:
            import omnivoice_tts

            resolved = omnivoice_tts.resolve_fix_omnivoice_script()
            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.resolve(), self.fix_script_path.resolve())
            norm_resolved = str(resolved).replace("\\", "/").lower()
            self.assertNotIn("tham-chieu", norm_resolved)
            self.assertNotIn("plans", norm_resolved)
        finally:
            if scripts_dir in sys.path:
                sys.path.remove(scripts_dir)
            if "omnivoice_tts" in sys.modules:
                del sys.modules["omnivoice_tts"]

    def test_omnivoice_tts_status_detects_fix_script(self):
        result = subprocess.run(
            [sys.executable, str(self.wrapper_path), "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"Status failed: {result.stderr}")
        data = json.loads(result.stdout)
        self.assertTrue(data.get("fix_omnivoice_available"))
        self.assertEqual(
            Path(data.get("fix_omnivoice_script")).resolve(),
            self.fix_script_path.resolve(),
        )

    @unittest.skipUnless(HAS_NUMPY, "numpy required for fix_omnivoice cleanup tests")
    def test_fix_omnivoice_cleans_wav_and_passes_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            input_wav = temp_path / "raw.wav"
            output_wav = temp_path / "corrected.wav"
            report_file = temp_path / "report.json"

            sample_rate = 24000
            # 1 second silence, 50ms low-volume noise pulse (-52 dBFS ~ 80 amplitude), 1 second silence
            silence_before = [0] * (sample_rate * 1)
            noise_pulse = [80] * int(sample_rate * 0.05)
            silence_after = [0] * (sample_rate * 1)
            samples = silence_before + noise_pulse + silence_after

            with wave.open(str(input_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                # Pack 16-bit LE
                data = bytearray()
                for sample in samples:
                    data.extend(int(sample).to_bytes(2, byteorder="little", signed=True))
                w.writeframes(bytes(data))

            result = subprocess.run(
                [
                    sys.executable,
                    str(self.fix_script_path),
                    "--input",
                    str(input_wav),
                    "--output",
                    str(output_wav),
                    "--report",
                    str(report_file),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, f"fix_omnivoice failed: {result.stderr}")
            self.assertTrue(output_wav.is_file())
            self.assertTrue(report_file.is_file())

            report_data = json.loads(report_file.read_text(encoding="utf-8"))
            self.assertTrue(report_data["verification"]["valid"])
            self.assertEqual(report_data["verification"]["outside_changed_samples"], 0)
            self.assertEqual(report_data["verification"]["inside_nonzero_samples"], 0)


if __name__ == "__main__":
    unittest.main()
