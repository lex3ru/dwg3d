"""Command line interface.

  python -m dwg3d build plan.dwg -o out/ [-c my_config.yaml]
  python -m dwg3d analyze plan.dwg        # layers + detected floors, no 3D
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

from .config import load_config
from .pipeline import analyze, run


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dwg3d")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build model.glb + metadata.json")
    b.add_argument("input")
    b.add_argument("-o", "--out", default="out")
    b.add_argument("-c", "--config", help="YAML/JSON config override")
    b.add_argument("--no-debug", action="store_true", help="skip debug PNGs")
    a = sub.add_parser("analyze", help="print layers and floor candidates")
    a.add_argument("input")
    a.add_argument("-c", "--config")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose or args.cmd == "build" else logging.WARNING,
                        format="%(message)s")

    if args.cmd == "build":
        meta = run(args.input, args.out, args.config, debug_png=not args.no_debug)
        print(f"\n{meta['model']}: {len(meta['floors'])} floors, {meta['triangles']} triangles, "
              f"{meta['elapsed_s']} s -> {Path(args.out).resolve()}")
        for f in meta["floors"]:
            print(f"  {f['id']:>4} L{f['level']:>3}  {f['name']:<32} elev {f['elevation']:>7.2f}  "
                  f"h {f['height']:.2f} ({f['height_source']})  {f['stats']['openings']}  rooms {f['stats']['rooms']}")
        for w in meta["warnings"]:
            print("  ! " + w)
    else:
        cfg = load_config(args.config)
        with tempfile.TemporaryDirectory() as tmp:
            d, cands, info = analyze(Path(args.input), Path(tmp), cfg)
        print(json.dumps({k: v for k, v in info.items() if k != "layers"}, ensure_ascii=False, indent=1))
        print("\nLayers:")
        for name, st in info["layers"].items():
            print(f"  {str(st['role'] or '-'):8} {st['count']:>6}  {name}")
        print("\nFloor candidates:")
        for c in cands:
            print(f"  {c.id:>4} {c.source:8} level={c.level} kind={c.kind} include={c.include} "
                  f"mark={c.mark} name={c.name!r}")


if __name__ == "__main__":
    sys.exit(main())
