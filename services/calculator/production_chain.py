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

    def expand(key: str, amount: Number, path: tuple[str, ...], depth: int) -> dict[str, Number]:
        if key in path:
            raise ProductionChainError("Циклический рецепт: " + " → ".join((*path, key)))
        if depth > max_depth:
            raise ProductionChainError("Превышена максимальная глубина производственной цепочки.")
        recipe = recipes_by_output.get(key)
        if recipe is None:
            return {key: amount}
        batches = math.ceil(amount / max(1, recipe.output_quantity))
        total: dict[str, Number] = {}
        for child, child_amount in recipe.materials.items():
            for raw, raw_amount in expand(
                child, child_amount * batches, (*path, key), depth + 1
            ).items():
                total[raw] = total.get(raw, 0) + raw_amount
        return total

    result: dict[str, Number] = {}
    for resource, amount in materials.items():
        for raw, raw_amount in expand(resource, amount, (), 0).items():
            result[raw] = result.get(raw, 0) + raw_amount
    return result
