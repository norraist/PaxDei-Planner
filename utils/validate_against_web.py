# planner/validate_against_web.py
from __future__ import annotations
import argparse, os, csv, glob, math
from typing import Dict, List, Tuple, Optional

COLS = [
    "Skill Level",
    "Success Chance",
    "XP (Success) Min",
    "XP (Success) Avg",
    "XP (Success) Max",
    "XP (Failure) Avg",
    "XP (Expected) Avg",
]

def _read_table_csv(path: str) -> List[Dict[str,str]]:
    with open(path, "r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        return list(rdr)

def _parse_int(s: str) -> Optional[int]:
    if s is None or s == "":
        return None
    s = s.strip()
    if s.endswith("+"): s = s[:-1]
    s = s.replace("%","")
    try:
        return int(s)
    except:
        return None

def _parse_float(s: str) -> Optional[float]:
    if s is None or s == "":
        return None
    try:
        return float(s)
    except:
        return None

def _align_by_level(pred_rows: List[Dict[str,str]], gold_rows: List[Dict[str,str]]):
    idx_pred = { r["Skill Level"]: r for r in pred_rows }
    idx_gold = { r["Skill Level"]: r for r in gold_rows }
    keys = sorted(set(idx_pred.keys()) & set(idx_gold.keys()), key=lambda k: (_parse_int(k) or 10**9, k))
    return keys, idx_pred, idx_gold

def _mae(a: float, b: float) -> float: return abs(a-b)
def _mape(a: float, b: float) -> float:
    denom = max(1.0, abs(b))
    return abs(a-b)/denom

def compare_tables(pred: List[Dict[str,str]], gold: List[Dict[str,str]], tolerances: Dict[str,float]) -> Tuple[int, List[Dict[str,str]]]:
    keys, ip, ig = _align_by_level(pred, gold)
    bad_rows: List[Dict[str,str]] = []
    for k in keys:
        pr, gr = ip[k], ig[k]
        # parse numbers
        s_p = _parse_float(pr.get("XP (Success) Avg","") or "0") or 0.0
        s_g = _parse_float(gr.get("XP (Success) Avg","") or "0") or 0.0
        e_p = _parse_float(pr.get("XP (Expected) Avg","") or "0") or 0.0
        e_g = _parse_float(gr.get("XP (Expected) Avg","") or "0") or 0.0
        f_p = _parse_float(pr.get("XP (Failure) Avg","") or "0") or 0.0
        f_g = _parse_float(gr.get("XP (Failure) Avg","") or "0") or 0.0

        ok = (
            _mae(s_p, s_g) <= max(tolerances["abs_success"], tolerances["pct_success"]*abs(s_g)) and
            _mae(e_p, e_g) <= max(tolerances["abs_expected"], tolerances["pct_expected"]*abs(e_g)) and
            _mae(f_p, f_g) <= tolerances["abs_failure"]
        )
        if not ok:
            bad_rows.append({
                "Skill Level": k,
                "Success Avg (ours)": f"{s_p:.0f}", "Success Avg (web)": f"{s_g:.0f}",
                "Expected Avg (ours)": f"{e_p:.0f}", "Expected Avg (web)": f"{e_g:.0f}",
                "Failure Avg (ours)": f"{f_p:.0f}",  "Failure Avg (web)": f"{f_g:.0f}",
            })
    return len(keys), bad_rows

def run(pred_dir: str, golden_cache: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    # tolerances (tweak if needed)
    tolerances = {
        "abs_success": 5.0,     # ±5 XP
        "pct_success": 0.02,    # ±2%
        "abs_expected": 5.0,    # ±5 XP
        "pct_expected": 0.02,   # ±2%
        "abs_failure": 3.0      # ±3 XP
    }

    pred_files = glob.glob(os.path.join(pred_dir, "*", "*.csv"))
    # Map recipe filename -> path for our predictions
    pred_by_file = { os.path.basename(p): p for p in pred_files }

    summary_path = os.path.join(out_dir, "web_validation_summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8") as fsum:
        wsum = csv.writer(fsum)
        wsum.writerow(["recipe_key","rows_compared","rows_out_of_tolerance","gold_path","pred_path"])

        # For each cached golden csv, try to find our prediction and compare
        gold_files = glob.glob(os.path.join(golden_cache, "*.csv"))
        for gpath in sorted(gold_files):
            fn = os.path.basename(gpath)            # recipe_xxx.csv
            ppath = pred_by_file.get(fn)
            if not ppath:
                wsum.writerow([fn, 0, "no_pred", gpath, ""])
                continue

            gold_rows = _read_table_csv(gpath)
            pred_rows = _read_table_csv(ppath)

            total, bad = compare_tables(pred_rows, gold_rows, tolerances)
            # write per-recipe diffs only if there are any
            if bad:
                diffp = os.path.join(out_dir, f"diff_{fn}")
                with open(diffp, "w", newline="", encoding="utf-8") as fd:
                    wd = csv.DictWriter(fd, fieldnames=list(bad[0].keys()))
                    wd.writeheader()
                    for r in bad: wd.writerow(r)
            wsum.writerow([fn, total, len(bad), gpath, ppath])

    print(f"Summary written to: {summary_path}")
    print("Tip: open only the diff_*.csv files that exist—those are the few with real discrepancies.")
