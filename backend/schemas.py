from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.orders.domain import Status


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ItemInput(Input):
    item_id: int | None = Field(default=None, gt=0)
    name: str = Field(default="", max_length=200)
    category: Literal["vehicle", "ammunition", "equipment", "material", "delivery", "other"]
    quantity: int = Field(gt=0, le=100000, strict=True)
    unit: Literal["item", "crate", "batch", "request"]
    recipe_key: str | None = Field(default=None, max_length=50)
    comment: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.item_id is None and (self.category not in {"delivery", "other"} or not self.name):
            raise ValueError("Выберите предмет каталога или опишите логистический запрос")
        if self.item_id is None and self.unit != "request":
            raise ValueError("Для свободного запроса используйте единицу request")
        if self.item_id is not None and self.unit == "request":
            raise ValueError("Для предмета выберите штуки, ящики или партии")
        if self.unit == "batch" and not self.recipe_key:
            raise ValueError("Для партии нужен конкретный рецепт")
        return self


class OrderInput(Input):
    idempotency_key: UUID
    items: list[ItemInput] = Field(min_length=1, max_length=30)
    delivery_location: str = Field(min_length=1, max_length=300)
    comment: str = Field(default="", max_length=2000)


class VersionInput(Input):
    version: int = Field(gt=0)


class TransitionInput(VersionInput):
    status: Status
    reason: str = Field(default="", max_length=1000)
    admin_override: bool = False


class NoteInput(Input):
    content: str = Field(min_length=1, max_length=4000)


class EditInput(VersionInput):
    items: list[ItemInput] = Field(min_length=1, max_length=30)
    delivery_location: str = Field(min_length=1, max_length=300)
    comment: str = Field(default="", max_length=2000)
