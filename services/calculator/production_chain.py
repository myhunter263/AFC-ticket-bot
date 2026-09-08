from __future__ import annotations

import math

from services.calculator.models import Number, RecipeInput


class ProductionChainError(ValueError):
    pass


def expand_resources(
    materials: dict[str, Number],
    recipes_by_output: dict[str, RecipeInput],
    *,
    max_depth: int = 20,
) -> dict[str, Number]:
    """Expand intermediate materials while detecting recipe cycles."""

    ordered: list[str] = []
    visited: set[str] = set()

    def visit(key: str, path: tuple[str, ...]) -> None:
        if key in path:
            raise ProductionChainError("Cyclic recipe: " + " -> ".join((*path, key)))
        if len(path) > max_depth:
            raise ProductionChainError("Production chain is too deep")
        if key in visited:
            return
        recipe = recipes_by_output.get(key)
        if recipe:
            if recipe.output_quantity <= 0 or any(v <= 0 for v in recipe.materials.values()):
                raise ProductionChainError("Invalid recipe quantities")
            for child in recipe.materials:
                visit(child, (*path, key))
        visited.add(key)
        ordered.append(key)

    for key, amount in materials.items():
        if amount < 0:
            raise ProductionChainError("Negative resource quantity")
        visit(key, ())
    demand = dict(materials)
    result: dict[str, Number] = {}
    # All consumers contribute demand before rounding a shared intermediate batch.
    for key in reversed(ordered):
        amount = demand.get(key, 0)
        recipe = recipes_by_output.get(key)
        if recipe is None:
            result[key] = amount
            continue
        batches = math.ceil(amount / recipe.output_quantity)
        for child, quantity in recipe.materials.items():
            demand[child] = demand.get(child, 0) + batches * quantity
    return result
