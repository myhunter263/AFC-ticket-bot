import pytest

from services.foxhole_api import FoxholeDataset
from services.recipe_audit_service import RecipeAuditService


def _dataset(recipes):
    return FoxholeDataset(
        items=[{
            "api_id": "foxholehq:tank", "api_name": "Tank", "is_vehicle": True,
            "mpf_available": True,
        }],
        recipes=recipes,
        categories=["vehicles"], source_version="Patch 65", source_updated_at=None,
        dataset_hash="test", resource_crate_sizes={"rmat": 20},
    )


def test_vehicle_recipe_units_pass_audit():
    report = RecipeAuditService.audit_dataset(_dataset([
        {"api_id": "foxholehq:tank", "production_method": "garage",
         "output_quantity": 1, "output_unit": "vehicle", "materials": {"rmat": 100}},
        {"api_id": "foxholehq:tank", "production_method": "mpf",
         "output_quantity": 1, "output_unit": "vehicle_crate", "materials": {"rmat": 300},
         "raw_data": {"vehicles_per_crate": 3}},
    ]))
    assert report.errors == []


@pytest.mark.parametrize("amount", (0, -1))
def test_zero_or_negative_price_is_rejected(amount):
    report = RecipeAuditService.audit_dataset(_dataset([
        {"api_id": "foxholehq:tank", "production_method": "garage",
         "output_quantity": 1, "output_unit": "vehicle", "materials": {"rmat": amount}},
        {"api_id": "foxholehq:tank", "production_method": "mpf",
         "output_quantity": 1, "output_unit": "vehicle_crate", "materials": {"rmat": 300},
         "raw_data": {"vehicles_per_crate": 3}},
    ]))
    assert report.errors
