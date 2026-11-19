#!/usr/bin/env python3
"""One command from a Halcyon script file to a finished news short and an approval pack.

    python mot-lenh.py <kich-ban.json> --out <run folder> [--chi-kiem]

The work is in halcyon_mot_lenh.py (standard library only); the contract and the runbook are in MOT-LENH.md."""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location('halcyon_mot_lenh', Path(__file__).resolve().with_name('halcyon_mot_lenh.py'))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(mod.main(sys.argv[1:]))
