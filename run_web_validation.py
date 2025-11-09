from __future__ import annotations

import argparse
from pathlib import Path

import bootstrap  # noqa: F401

from utils.validate_against_web import run as validate_against_web
from utils.web_golden_fetch_json import fetch_from_file

DEFAULT_KEYS = Path("utils/recipes.txt")
DEFAULT_GOLD = Path("utils/golden_json_cache")
DEFAULT_PRED = Path("out/xp_tables")
DEFAULT_OUT = Path("out/web_validation")


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Fetch golden recipe data (optional) and validate our XP tables without juggling multiple CLIs."
    )
    ap.add_argument("--keys-file", default=str(DEFAULT_KEYS), help="Path to recipes.txt (default utils/recipes.txt)")
    ap.add_argument("--gold-cache", default=str(DEFAULT_GOLD), help="Directory for golden JSON (default utils/golden_json_cache)")
    ap.add_argument("--pred-dir", default=str(DEFAULT_PRED), help="Directory with generated XP tables (default out/xp_tables)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Directory to write validation output (default out/web_validation)")
    fetch_grp = ap.add_argument_group("fetch options")
    fetch_grp.add_argument("--skip-fetch", action="store_true", help="Skip contacting the CDN, reuse existing golden cache")
    fetch_grp.add_argument("--delay", type=float, default=1.5, help="Minimum delay between CDN requests (default 1.5s)")
    fetch_grp.add_argument("--jitter", type=float, default=0.7, help="Additional random delay added to each request (default 0.7s)")
    fetch_grp.add_argument("--version", default=None, help="Optional CDN version query parameter")
    fetch_grp.add_argument("--host", default=None, help="Force a specific CDN host instead of rotating")
    fetch_grp.add_argument("--try-all", action="store_true", help="Try all known hosts for each request (default: only data2)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    keys_file = Path(args.keys_file).resolve()
    gold_cache = Path(args.gold_cache).resolve()
    pred_dir = Path(args.pred_dir).resolve()
    out_dir = Path(args.out).resolve()

    if not args.skip_fetch:
        fetch_from_file(
            str(keys_file),
            str(gold_cache),
            delay=args.delay,
            jitter=args.jitter,
            version=args.version,
            host=args.host,
            try_all=args.try_all,
        )
    else:
        print("[info] Skipping CDN fetch; reusing existing golden cache.")

    validate_against_web(str(pred_dir), str(gold_cache), str(out_dir))
    summary = out_dir / "web_validation_summary.csv"
    print(f"[done] Validation summary: {summary}")


if __name__ == "__main__":
    main()
