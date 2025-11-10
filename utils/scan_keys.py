import json
from pathlib import Path

from bootstrap import _ensure_src_on_path  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "source_data" / "staticdatabundle" / "StaticDataBundle.json"
data = json.load(DATA_PATH.open())
stack=[(data,None)]
keys=set()
while stack:
    obj, cur = stack.pop()
    if isinstance(obj, dict):
        key = obj.get('Key') or obj.get('ItemKey') or obj.get('Id') or cur
        if isinstance(key, str) and key.lower().startswith('item_material_'):
            keys.add(key)
        for k,v in obj.items():
            if isinstance(v,(dict,list)):
                stack.append((v, k if isinstance(k,str) else cur))
    elif isinstance(obj,list):
        for v in obj:
            if isinstance(v,(dict,list)):
                stack.append((v, cur))
print(len(keys))
print(list(sorted(keys))[:5])
