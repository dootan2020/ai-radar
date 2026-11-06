"""Stand-in batch CLI that starts a grandchild holding its stdout/stderr, then hangs; never calls a model.

Like an npm .cmd shim running node, or agy starting MCP helpers: ending only this process leaves the grandchild
holding the pipes open. Usage: pipe-holder.py <pid-file> <grandchild-seconds>. The pid file gets this process's
PID and the grandchild's, one per line.
"""

import os
import subprocess
import sys
import time

seconds = float(sys.argv[2])
grandchild = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"],
                              stdout=sys.stdout, stderr=sys.stderr)
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(f"{os.getpid()}\n{grandchild.pid}\n")
time.sleep(seconds)
