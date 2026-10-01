"""Real bind-conflict regression using an owned ephemeral port, never 8787."""

from pathlib import Path
import subprocess
import sys
import unittest

import serve


class ServerTests(unittest.TestCase):
    def test_second_process_cannot_bind_an_owned_listener(self):
        with serve.LocalServer(("127.0.0.1", 0), serve.Handler) as listener:
            port = listener.server_address[1]
            result = subprocess.run(
                [sys.executable, "-c", "import serve; "
                 f"serve.LocalServer(('127.0.0.1', {port}), serve.Handler)"],
                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                text=True, timeout=5,
            )
            self.assertNotEqual(result.returncode, 0, "Second process bound an occupied port")
            self.assertIn("OSError", result.stderr)


if __name__ == "__main__":
    unittest.main()
