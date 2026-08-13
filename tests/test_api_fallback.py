import pytest

from services.foxhole_api import FoxholeAPIClient, FoxholeAPIError
from services.order_preview_service import OrderPreviewService


@pytest.mark.asyncio
async def test_empty_api_url_fails_cleanly_and_local_catalog_still_works(catalog):
    with pytest.raises(FoxholeAPIError):
        await FoxholeAPIClient("").fetch_items()

    order = OrderPreviewService(catalog).parse("15 аргенти")
    assert len(order.items) == 1
    assert order.items[0].resolved.item.ru_name == "Аргенти"
