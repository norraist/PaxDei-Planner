#!/usr/bin/env python3
"""
Generate a Pax Dei leveling profile JSON from StaticDataBundle.json + localisation_en.json,
with optional merge from an existing profile to preserve your current levels/XP/targets and owned crafters.

- Skills are derived strictly from recipes where IsDev == false.
- Crafters are taken from the CRAFTER block where IsDev == false.
- If --base is provided, any matching skills/crafters in the output will inherit:
    * skills[<key>].current_level, current_xp, target_level (and name if you customized it)
    * crafters[<key>].owned (and name if you customized it)
  Entries that no longer exist in the latest game data are dropped by default.

Usage:
  python generate_profile.py --static data/StaticDataBundle.json --loc data/localisation_en.json --out profile.json [--base existing_profile.json]
"""
import json, argparse, re, sys
from typing import Dict, Any, Optional

def index_localization(obj):
    idx = {}
    def visit(x):
        if isinstance(x, dict):
            key = x.get("Key") or x.get("key") or x.get("_LocalizationNameKey") or x.get("_LocalizationDescriptionKey")
            text = x.get("Text") or x.get("text") or x.get("Name") or x.get("name") or x.get("Description") or x.get("description")
            if key and text:
                idx[str(key)] = str(text)
            for v in x.values():
                visit(v)
        elif isinstance(x, list):
            for v in x:
                visit(v)
    visit(obj)
    return idx

def collect_real_skills(static):
    real = set()
    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str) and k.startswith("recipe_") and isinstance(v, dict):
                    if not bool(v.get("IsDev", False)):
                        skill = v.get("SkillRequired") or v.get("Skill") or ""
                        if isinstance(skill, str) and skill:
                            real.add(skill)
                else:
                    walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(static)
    return sorted(real)

def prettify_skill(sk):
    s = sk
    if s.lower().startswith("skill_"):
        s = s[6:]
    s = s.replace("_", " ")
    return s.title()

def collect_nondev_crafters(static, loc_idx):
    crafters = {}
    def human_name(node):
        if isinstance(node, dict):
            nk = node.get("LocalizationNameKey") or node.get("_LocalizationNameKey")
            if isinstance(nk, str) and nk in loc_idx:
                return loc_idx[nk]
            # fallbacks
            for k, v in node.items():
                if isinstance(v, str) and k.lower() in ("name","displayname","title"):
                    return v
            # scan for localization-like fields
            for k, v in node.items():
                if isinstance(v, (str, int)):
                    ks = str(k).lower()
                    if any(tok in ks for tok in ("localization","loc","display")):
                        txt = loc_idx.get(str(v))
                        if txt:
                            return txt
        return None

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "CRAFTER" and isinstance(v, dict):
                    for ck, cv in v.items():
                        if not isinstance(cv, dict):
                            continue
                        if bool(cv.get("IsDev", False)):
                            continue
                        name = human_name(cv) or re.sub(r"[_]+"," ", str(ck)).title()
                        crafters[str(ck)] = {"name": name, "owned": False}
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
    walk(static)
    return crafters

def merge_base(new_profile: Dict[str, Any], base_path: str) -> Dict[str, Any]:
    try:
        with open(base_path, "r", encoding="utf-8") as f:
            base = json.load(f)
    except Exception as e:
        print(f"[warn] Could not read base profile '{base_path}': {e}")
        return new_profile

    # Support both nested and legacy base formats.
    base_skills = {}
    if "skills" in base:
        base_skills = base["skills"]
    else:
        # legacy: flatten into nested style
        cl = base.get("current_level", {})
        cx = base.get("current_xp", {})
        tl = base.get("target_level", base.get("targets", {}))
        for sk, lvl in cl.items():
            base_skills[sk] = {
                "name": sk,
                "current_level": int(lvl),
                "current_xp": int(cx.get(sk, 0)),
                "target_level": int(tl.get(sk, int(lvl)+5))
            }

    base_crafters = base.get("crafters", {})
    if not base_crafters and "owned_stations" in base:
        base_crafters = {s: {"name": s, "owned": True} for s in base["owned_stations"]}

    # Merge into new profile
    merged = {
        "skills": {},
        "crafters": {},
        "premium_account": bool(base.get("premium_account", new_profile.get("premium_account", False))),
        "avoid_relics": bool(base.get("avoid_relics", new_profile.get("avoid_relics", False))),
        "max_cross_skill_gap": int(base.get("max_cross_skill_gap", new_profile.get("max_cross_skill_gap", 5)))
    }

    # Skills: include only keys present in new_profile['skills'] (drop removed ones), carry user values
    for sk, node in new_profile["skills"].items():
        merged_node = dict(node)  # defaults
        if sk in base_skills and isinstance(base_skills[sk], dict):
            b = base_skills[sk]
            # Carry over user state when present
            merged_node["current_level"] = int(b.get("current_level", merged_node["current_level"]))
            merged_node["current_xp"]     = int(b.get("current_xp", merged_node["current_xp"]))
            merged_node["target_level"]   = int(b.get("target_level", merged_node["target_level"]))
            # If user customized display name, prefer it
            if isinstance(b.get("name"), str) and b.get("name").strip():
                merged_node["name"] = b["name"]
        merged["skills"][sk] = merged_node

    # Crafters: include only new non-dev crafters; carry `owned` and name if customized
    for ck, node in new_profile["crafters"].items():
        merged_node = dict(node)
        if ck in base_crafters and isinstance(base_crafters[ck], dict):
            b = base_crafters[ck]
            if "owned" in b:
                merged_node["owned"] = bool(b["owned"])
            if isinstance(b.get("name"), str) and b.get("name").strip():
                merged_node["name"] = b["name"]
        merged["crafters"][ck] = merged_node

    return merged

def _lookup_loc(loc_idx: Dict[str, str], loc_raw: Dict[str, Any], key: str) -> Optional[str]:
    if key in loc_idx:
        return loc_idx[key]
    val = loc_raw.get(key)
    if isinstance(val, str):
        return val
    return None

def apply_localized_names(profile: Dict[str, Any], loc_idx: Dict[str, str], loc_raw: Dict[str, Any]) -> None:
    for sk, node in profile.get("skills", {}).items():
        loc_key = f"{sk}_LocalizationNameKey"
        name = _lookup_loc(loc_idx, loc_raw, loc_key)
        if name:
            node["name"] = name
    for ck, node in profile.get("crafters", {}).items():
        loc_key = f"{ck}_LocalizationNameKey"
        name = _lookup_loc(loc_idx, loc_raw, loc_key)
        if name:
            node["name"] = name

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--static", required=True, help="Path to StaticDataBundle.json")
    ap.add_argument("--loc", required=True, help="Path to localisation_en.json")
    ap.add_argument("--out", required=True, help="Path to output profile JSON")
    ap.add_argument("--base", required=False, help="Optional base profile to merge (preserves your current state)")
    args = ap.parse_args()

    with open(args.static, "r", encoding="utf-8") as f:
        static = json.load(f)
    with open(args.loc, "r", encoding="utf-8") as f:
        loc = json.load(f)

    loc_idx = index_localization(loc)
    skills = collect_real_skills(static)
    skills_obj = { sk: {"name": prettify_skill(sk), "current_level": 1, "current_xp": 0, "target_level": 40} for sk in skills }
    crafters = collect_nondev_crafters(static, loc_idx)

    profile = {"skills": skills_obj, "crafters": crafters, "premium_account": False, "avoid_relics": False, "max_cross_skill_gap": 5}

    if args.base:
        profile = merge_base(profile, args.base)

    apply_localized_names(profile, loc_idx, loc)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    print(f"Wrote profile to {args.out} with {len(profile['skills'])} skills and {len(profile['crafters'])} crafters."
          + (" (merged from base)" if args.base else ""))

if __name__ == "__main__":
    main()
