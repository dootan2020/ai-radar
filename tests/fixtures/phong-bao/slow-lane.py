"""Stand-in batch CLI for timeout tests: answers every row, but hangs on a row whose id starts with "hang".

Reads the prompt on stdin; the rows are the JSON array on its last line. With --codex it answers as
`codex exec --json` events do. It never calls a model or the network.
"""

import json
import sys
import time

rows = json.loads(sys.stdin.read().rsplit("\n", 1)[-1])
if any(str(row.get("id", "")).startswith("hang") for row in rows) and "--never-hang" not in sys.argv:
    time.sleep(120)
answer = json.dumps({"stories": [{"id": row["id"], "lane": sys.argv[-1]} for row in rows]})
if "--codex" in sys.argv:
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": answer}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}))
else:
    print(answer)
