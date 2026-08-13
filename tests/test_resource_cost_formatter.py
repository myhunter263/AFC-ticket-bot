from services.resource_cost_formatter import ResourceCostFormatter


def test_formats_full_and_partial_resource_crates():
    formatter = ResourceCostFormatter({"bmat": 100, "rmat": 20})
    assert formatter.resource("bmat", 200) == "200 BMat или 2 ящика BMat"
    assert formatter.resource("bmat", 130) == "130 BMat или 1 ящик + 30 BMat"
    assert formatter.resource("rmat", 40) == "40 RMat или 2 ящика RMat"


def test_formats_multiple_resources_independently():
    text = ResourceCostFormatter({"bmat": 100, "rmat": 20}).materials(
        {"bmat": 130, "rmat": 40}
    )
    assert text == (
        "130 BMat или 1 ящик + 30 BMat + "
        "40 RMat или 2 ящика RMat"
    )
