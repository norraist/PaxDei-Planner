from __future__ import annotations
from typing import Dict
from .schemas import Recipe

def craft_cost(recipe: Recipe, material_weights: Dict[str, float]) -> float:
    # Sum of (ingredient qty × weight). Default weight=1.0 if not provided.
    total = 0.0
    for item, qty in (recipe.ingredients or {}).items():
        w = material_weights.get(item, 1.0)
        total += w * float(qty)
    return total if total > 0 else 1.0  # avoid division by zero
