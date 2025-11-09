import json
from pathlib import Path

from bootstrap import _ensure_src_on_path  # noqa: F401

DATA_PATH = Path(__file__).resolve().parent / "src" / "paxdei_planner" / "data" / "StaticDataBundle.json"
data = json.load(DATA_PATH.open())
stack=[data]
found=None
while stack:
    obj=stack.pop()
    if isinstance(obj, dict):
        if 'item_material_malt' in obj:
            found=obj['item_material_malt']
            break
        for v in obj.values():
            if isinstance(v, (dict, list)):
                stack.append(v)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                stack.append(v)
if not found:
    print('not found')
else:
    print(found.keys())
    print(found.get('Categories'))
    print(found.get('LocalizationNameKey'), found.get('LocalizationDescriptionKey'))
