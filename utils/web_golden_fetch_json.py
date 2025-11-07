from __future__ import annotations
import argparse, os, time, random, json
from typing import Optional
import requests


DEFAULT_HOSTS = ["data2.gtcdn.info", "data1.gtcdn.info", "data3.gtcdn.info"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"

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
            # DNS / connect / timeouts → try next host
            last_err = e
            continue
    raise last_err or RuntimeError("All CDN hosts failed")

def main():
    ap = argparse.ArgumentParser(description="Fetch per-recipe JSON from the Pax Dei CDN (polite).")
    ap.add_argument("--keys-file", required=True, help="Text file with one recipe key per line")
    ap.add_argument("--out", required=True, help="Directory to write JSON files (e.g., golden_json_cache)")
    ap.add_argument("--delay", type=float, default=0.8, help="Base delay between requests (default 0.8s)")
    ap.add_argument("--version", default=None, help="Optional version query param (usually not needed)")
    ap.add_argument("--host", default=None, help="Force a single CDN host, e.g. data2.gtcdn.info")
    ap.add_argument("--try-all", action="store_true", help="Try all known hosts in order (default when --host not set)")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    sess = requests.Session()

    with open(args.keys_file, "r", encoding="utf-8") as f:
        keys = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    # Host selection
    hosts = [args.host] if args.host else DEFAULT_HOSTS
    if args.host:
        print(f"[info] Forcing host: {args.host}")
    elif not args.try_all:
        # default to the most reliable
        hosts = ["data2.gtcdn.info"]

    for k in keys:
        outp = os.path.join(args.out, f"{k}.json")
        if os.path.exists(outp):
            print(f"[cache] {k}")
            continue
        try:
            data = fetch_json(k, sess, args.version, hosts)
            with open(outp, "w", encoding="utf-8") as w:
                json.dump(data, w, indent=2, ensure_ascii=False)
            print(f"[ok] {k} -> {outp}")
        except Exception as e:
            print(f"[err] {k}: {e}")
        time.sleep(max(0.0, args.delay + random.uniform(0, 0.4)))

if __name__ == "__main__":
    main()
