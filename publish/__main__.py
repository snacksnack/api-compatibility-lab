"""Build the published site.

    uv run --group site python -m publish --out site

Run by the Pages workflow on every push to main (ADR 0008). It reads only
committed artifacts, so it needs no credentials, no network and no container.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

from publish.render import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="publish")
    parser.add_argument("--out", default="site",
                        help="directory to write the site into (default: site)")
    parser.add_argument("--clean", action="store_true",
                        help="empty the output directory first")
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", ""),
                        help="commit to credit in the footer")
    args = parser.parse_args(argv)

    out = pathlib.Path(args.out)
    if args.clean and out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        written = build(out, commit=args.commit)
    except ValueError as problem:
        print(f"FAIL: {problem}", file=sys.stderr)
        return 1

    for path in written:
        print(f"wrote {path}")
    print(f"\n{len(written)} page(s) in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
