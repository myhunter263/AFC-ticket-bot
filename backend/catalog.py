from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import select, text

from backend.auth import Principal, principal, require
from backend.events import emit
from backend.schemas import Input
from database.models import AuditLog, FoxholeItem, FoxholeRecipeOverride
from services.calculator.service import CalculatorService
from services.item_catalog_service import ItemCatalogService
from services.item_resolver import ItemResolver
from services.foxhole_types import ResolvedItem
from services.item_sync_service import ItemSyncService

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


def audit(session, actor, item_id, action, details):
    session.add(AuditLog(guild_id=actor.guild_id, user_id=actor.user_id, user_name=actor.name,
        action=action, target_type="catalog_item", target_id=item_id, details=details))


@router.get("")
async def catalog(request: Request, search: str = Query("", max_length=200),
                  offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=200),
                  actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        rows = await ItemCatalogService.get_catalog(session, actor.guild_id)
        override_rows = (await session.scalars(select(FoxholeRecipeOverride).where(
            FoxholeRecipeOverride.guild_id == actor.guild_id))).all()
        if search:
            resolved = ItemResolver(rows).resolve(search)
            matches = [resolved.item] if isinstance(resolved, ResolvedItem) else [r.item for r in resolved.candidates]
            remaining = [r for r in rows if r not in matches and search.casefold() in (r.api_name + " " + r.ru_name).casefold()]
            rows = matches + remaining
        return [{"id": r.id, "api_id": r.api_id, "name": r.ru_name, "api_name": r.api_name,
                 "category": r.category, "crate_size": r.crate_size, "image_url": r.image_url,
                 "unit": CalculatorService.calculation_unit(r), "aliases": r.aliases,
                 "recipes": [{"key": p.key, "building": p.building, "unit": p.output_unit} for p in CalculatorService.recipes(r, [o for o in override_rows if o.item_id == r.id])]}
                for r in rows[offset:offset + limit]]


class CalculationInput(Input):
    item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, le=100000)
    unit: Literal["item", "crate"] = "item"
    recipe_choices: dict[str, str] = Field(default_factory=dict, max_length=100)


@router.post("/calculate")
async def calculate(value: CalculationInput, request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        rows = await ItemCatalogService.get_catalog(session, actor.guild_id)
        item = next((r for r in rows if r.id == value.item_id), None)
        if item is None:
            raise HTTPException(404, "Предмет не найден")
        overrides = (await session.scalars(select(FoxholeRecipeOverride).where(
            FoxholeRecipeOverride.guild_id == actor.guild_id,
        ))).all()
        from services.calculator.planning import calculate_plan
        return calculate_plan(item, value.quantity, rows, overrides, unit=value.unit, choices=value.recipe_choices)


@router.get("/status")
async def status(request: Request, actor: Principal = Depends(principal)):
    async with request.app.state.sessions() as session:
        result = await ItemSyncService.status(session, actor.guild_id)
        await session.commit()
        return result


@router.post("/refresh")
async def refresh(request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        locked = await session.scalar(text("SELECT pg_try_advisory_xact_lock(7410091)"))
        if not locked:
            raise HTTPException(409, "Каталог уже обновляется")
        result = await ItemSyncService.sync(session, actor.guild_id)
        await ItemCatalogService.ensure_seed(session, actor.guild_id)
        await emit(session, actor.guild_id, "foxholehq.cache_updated", {"success": result.success})
        await session.commit()
        return asdict(result)


class AliasInput(Input):
    alias: str = Field(min_length=1, max_length=200)


@router.post("/{item_id}/aliases")
async def alias(item_id: int, value: AliasInput, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        row = await ItemCatalogService.get_localization(session, actor.guild_id, item_id)
        if row is None:
            raise HTTPException(404, "Локализация не найдена")
        try:
            await ItemCatalogService.add_alias(session, row, value.alias, actor.user_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        audit(session, actor, item_id, "catalog.alias_added", {"alias": value.alias})
        await session.commit()
        return {"saved": True}


@router.delete("/{item_id}/aliases")
async def remove_alias(item_id: int, value: AliasInput, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        row = await ItemCatalogService.get_localization(session, actor.guild_id, item_id)
        if row is None:
            raise HTTPException(404, "Локализация не найдена")
        removed = await ItemCatalogService.remove_alias(session, row, value.alias)
        audit(session, actor, item_id, "catalog.alias_removed", {"alias": value.alias, "removed": removed})
        await session.commit()
        return {"removed": removed}


class OverrideInput(Input):
    method: str = Field(min_length=1, max_length=50)
    building: str = Field(min_length=1, max_length=100)
    materials: dict[str, float]
    output_quantity: int = Field(gt=0, le=100000)
    output_unit: Literal["item", "crate"]
    enabled: bool = True


@router.put("/{item_id}/override")
async def override(item_id: int, value: OverrideInput, request: Request, actor: Principal = Depends(principal)):
    import math
    require(actor, "ADMIN")
    if not value.materials or any(not k or not math.isfinite(v) or v <= 0 for k, v in value.materials.items()):
        raise HTTPException(422, "Материалы должны иметь положительные конечные количества")
    async with request.app.state.sessions() as session:
        item = await session.get(FoxholeItem, item_id)
        if item is None:
            raise HTTPException(404, "Предмет не найден")
        await session.execute(select(FoxholeItem).where(FoxholeItem.id == item_id).with_for_update())
        row = await session.scalar(select(FoxholeRecipeOverride).where(FoxholeRecipeOverride.guild_id == actor.guild_id,
            FoxholeRecipeOverride.item_id == item_id, FoxholeRecipeOverride.production_method == value.method))
        if row is None:
            row = FoxholeRecipeOverride(guild_id=actor.guild_id, item_id=item_id, production_method=value.method, created_by=actor.user_id)
            session.add(row)
        for key, val in value.model_dump(exclude={"method"}).items():
            setattr(row, key, val)
        audit(session, actor, item_id, "catalog.override_updated", value.model_dump())
        await emit(session, actor.guild_id, "catalog.override_updated", {"item_id": item_id})
        await session.commit()
        return {"saved": True}


@router.get("/{item_id}/overrides")
async def overrides(item_id: int, request: Request, actor: Principal = Depends(principal)):
    require(actor, "ADMIN", "MANAGER")
    async with request.app.state.sessions() as session:
        rows = (await session.scalars(select(FoxholeRecipeOverride).where(
            FoxholeRecipeOverride.guild_id == actor.guild_id, FoxholeRecipeOverride.item_id == item_id))).all()
        return [{"method": r.production_method, "building": r.building, "materials": r.materials,
                 "output_quantity": r.output_quantity, "output_unit": r.output_unit, "enabled": r.enabled} for r in rows]


@router.delete("/{item_id}/override/{method}")
async def remove_override(item_id: int, method: str, request: Request, actor: Principal = Depends(principal)):
    from sqlalchemy import delete
    require(actor, "ADMIN")
    async with request.app.state.sessions() as session:
        result = await session.execute(delete(FoxholeRecipeOverride).where(
            FoxholeRecipeOverride.guild_id == actor.guild_id, FoxholeRecipeOverride.item_id == item_id,
            FoxholeRecipeOverride.production_method == method))
        audit(session, actor, item_id, "catalog.override_removed", {"method": method})
        await emit(session, actor.guild_id, "catalog.override_updated", {"item_id": item_id})
        await session.commit()
        return {"removed": result.rowcount > 0}
