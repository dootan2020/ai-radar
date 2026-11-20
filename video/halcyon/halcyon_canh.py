"""Producer of the `scene3d` beat (step `canh:<ref>` of halcyon_mot_lenh.py): `halcyon_canh.py run --job <job.json> --out <folder>` writes
<folder>/clip.json and clip.mp4. The work is in scene3d/ (canh.py, canh.mjs, giao-thuc.js); see scene3d/README.md."""
import importlib.util
import sys
from pathlib import Path

CLIP_PRODUCER = 1

_p = Path(__file__).resolve().parent / 'scene3d' / 'canh.py'      # loaded by path: the chain runs this file with python -I (no script folder on sys.path)
_s = importlib.util.spec_from_file_location('halcyon_scene3d_canh', _p)
canh = importlib.util.module_from_spec(_s)
_s.loader.exec_module(canh)

if __name__ == '__main__':
    sys.exit(canh.main())
