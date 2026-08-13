import pytest

from services.resource_cost_formatter import (
    ResourceCostFormatter,
    calculate_required_resource_crates,
)


def test_formats_full_and_partial_resource_crates():
    formatter = ResourceCostFormatter({"bmat": 100, "rmat": 20})
    assert formatter.resource("bmat", 200) == "200 BMat или 2 ящика BMat"
    assert formatter.resource("bmat", 130) == "130 BMat или 2 ящика BMat"
    assert formatter.resource("rmat", 40) == "40 RMat или 2 ящика RMat"


def test_formats_multiple_resources_independently():
    text = ResourceCostFormatter({"bmat": 100, "rmat": 20}).materials(
        {"bmat": 130, "rmat": 40}
    )
    assert text == (
        "130 BMat или 2 ящика BMat + "
        "40 RMat или 2 ящика RMat"
    )


@pytest.mark.parametrize(
    ("amount", "expected"),
    ((0, 0), (1, 1), (50, 1), (80, 1), (99, 1), (100, 1),
     (101, 2), (150, 2), (180, 2), (199, 2), (200, 2), (201, 3)),
)
def test_required_resource_crates_always_rounds_up(amount, expected):
    assert calculate_required_resource_crates(amount, 100) == expected


def test_required_resource_crates_rejects_invalid_values():
    with pytest.raises(ValueError):
        calculate_required_resource_crates(-1, 100)
    with pytest.raises(ValueError):
        calculate_required_resource_crates(1, 0)
