"""Offline sizing of private approved samples; prints counts, never publisher text.

Run: python tests/measure_summary_inputs.py plans/mau-tom-tat
No tokenizer/model/network call is made. Ratios are planning assumptions only.
"""

import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar import summary_gemini as gemini
from radar.summary_pipeline import parse_article
from radar.summary_sources import source_record, primary_link, fit_inputs


def measure(directory):
    directory = Path(directory)
    sources = json.loads((directory / "extracted/sources.json").read_text(encoding="utf-8"))
    sources = {s["id"]: s for s in sources}
    outputs = json.loads((directory / "sample-output.json").read_text(encoding="utf-8"))
    parsers = {sid: parse_article((directory / f"input/{sid}.html").read_text(encoding="utf-8"), s["url"])
               for sid, s in sources.items()}
    rows = []
    for sid, output in zip(("01", "03", "05", "06"), outputs):
        source, parser = sources[sid], parsers[sid]
        text = "\n".join(parser.parts)
        records = [source_record("outlet", "outlet", source["url"], source["title"], source["publisher"], text)]
        primary = primary_link(parser.links, source["url"], source["title"], text)
        linked = next((s for s in sources.values() if s["url"] == primary), None)
        if linked:
            records.append(source_record("primary", "primary", primary, "", "",
                                         "\n".join(parsers[linked["id"]].parts)))
        inputs = fit_inputs({"id": output["id"], "sources": records,
                             "missing_primary": bool(primary and not linked),
                             "linked_primary": {"url": primary, "name": linked["publisher"]} if linked else None},
                            gemini.MAX_STORY_INPUT_CHARS)
        body = gemini.request_body([inputs])
        chars = len(json.dumps(body, ensure_ascii=False))
        wire_bytes = len(gemini.encode_request(body))
        full_output = {k: v for k, v in output.items() if k not in {"short_vi", "takeaway_vi"}}
        output_chars = len(json.dumps(full_output, ensure_ascii=False))
        rows.append({"sample": sid, "source_chars": sum(len(p["text"]) for s in inputs["sources"] for p in s["paragraphs"]),
                     "request_bytes": wire_bytes, "reservation_tokens": wire_bytes + gemini.MAX_OUTPUT_TOKENS,
                     "input_estimate": [math.ceil(chars / 4), math.ceil(chars / 3)],
                     "output_estimate": [math.ceil(output_chars / 3), math.ceil(output_chars / 1.8)]})
    return rows


if __name__ == "__main__":
    print(json.dumps(measure(sys.argv[1]), indent=2))
