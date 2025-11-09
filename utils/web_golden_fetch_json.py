from __future__ import annotations

import argparse
import json
import os
import random
import time
from typing import Iterable, Optional

import requests

DEFAULT_HOSTS = ["data2.gtcdn.info", "data1.gtcdn.info", "data3.gtcdn.info"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"


def _polite_sleep(base: float, jitter: float) -> None:
    """Sleep base + random(0, jitter) seconds between network calls."""
    extra = random.uniform(0.0, max(0.0, jitter))
    delay = max(0.0, base) + extra
    time.sleep(delay)


def fetch_json(recipe_key: str, session: requests.Session, version: Optional[str], hosts: list[str]) -> dict:
    last_err = None
    for host in hosts:
        base = f"https://{host}/paxdei/data/en/recipe/{recipe_key}.json"
        url = f"{base}?version={version}" if version else base
        try:
            r = session.get(
                url,
                headers={
                    "User-Agent": UA,
                    "Accept": "application/json",
                    "Origin": "https://paxdei.gaming.tools",
                    "Referer": "https://paxdei.gaming.tools/",
                    "Sec-GPC": "1",
                },
                timeout=20,
            )
            if r.status_code == 200:
                return r.json()
            # try next host on any non-200
            last_err = RuntimeError(f"{host} -> HTTP {r.status_code}")
        except requests.exceptions.RequestException as e:
            # DNS / connect / timeouts – try next host
            last_err = e
            continue
    raise last_err or RuntimeError("All CDN hosts failed")


def fetch_from_keys(
    keys: Iterable[str],
    out_dir: str,
    *,
    delay: float = 1.5,
    jitter: float = 0.7,
    version: Optional[str] = None,
    host: Optional[str] = None,
    try_all: bool = False,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    sess = requests.Session()

    hosts = [host] if host else DEFAULT_HOSTS
    if host:
        print(f"[info] Forcing host: {host}")
    elif not try_all:
        hosts = ["data2.gtcdn.info"]

    for k in keys:
        if not k or k.startswith("#"):
            continue
        outp = os.path.join(out_dir, f"{k}.json")
        if os.path.exists(outp):
            print(f"[cache] {k}")
            continue
        try:
            data = fetch_json(k, sess, version, hosts)
            with open(outp, "w", encoding="utf-8") as w:
                json.dump(data, w, indent=2, ensure_ascii=False)
            print(f"[ok] {k} -> {outp}")
        except Exception as e:
            print(f"[err] {k}: {e}")
        finally:
            _polite_sleep(delay, jitter)


def fetch_from_file(
    keys_file: str,
    out_dir: str,
    *,
    delay: float = 1.5,
    jitter: float = 0.7,
    version: Optional[str] = None,
    host: Optional[str] = None,
    try_all: bool = False,
) -> None:
    with open(keys_file, "r", encoding="utf-8") as f:
        keys = [line.strip() for line in f if line.strip()]
    fetch_from_keys(
        keys,
        out_dir,
        delay=delay,
        jitter=jitter,
        version=version,
        host=host,
        try_all=try_all,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch per-recipe JSON from the Pax Dei CDN (politely throttled).")
    ap.add_argument("--keys-file", required=True, help="Text file with one recipe key per line")
    ap.add_argument("--out", required=True, help="Directory to write JSON files (e.g., golden_json_cache)")
    ap.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Minimum delay between requests in seconds (default 1.5)",
    )
    ap.add_argument(
        "--jitter",
        type=float,
        default=0.7,
        help="Additional random delay (0..jitter seconds, default 0.7)",
    )
    ap.add_argument("--version", default=None, help="Optional version query param (usually not needed)")
    ap.add_argument("--host", default=None, help="Force a single CDN host, e.g. data2.gtcdn.info")
    ap.add_argument("--try-all", action="store_true", help="Try all known hosts in order (default when --host not set)")
    args = ap.parse_args()

    fetch_from_file(
        args.keys_file,
        args.out,
        delay=args.delay,
        jitter=args.jitter,
        version=args.version,
        host=args.host,
        try_all=args.try_all,
    )


if __name__ == "__main__":
    main()
