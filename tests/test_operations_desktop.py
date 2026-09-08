import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication, QLineEdit
from desktop.pages.operations import InventoryPage, ProductionPage, OperationForm, amount


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


def fake_api():
    return SimpleNamespace(request=Mock(), error=SimpleNamespace(emit=Mock()))


def test_reservation_action_uses_version_and_no_local_balance_change(qt):
    api = fake_api(); page = InventoryPage(api)
    row = {"id": 12, "order_id": 4, "quantity": 20, "state": "ACTIVE", "version": 3}
    page.reservations.loaded([row]); page.reservations.table.selectRow(0)
    page.finish_reservation("consume")
    assert api.request.call_args.args == ("POST", "/api/v1/inventory/reservations/12")
    assert api.request.call_args.kwargs["data"] == {"version": 3, "action": "consume"}
    assert page.reservations.model.rows[0]["state"] == "ACTIVE"
    page.close()


def test_production_claim_sends_backend_request(qt):
    api = fake_api(); page = ProductionPage(api)
    page.loaded([{"id": 7, "status": "PLANNED", "version": 1, "quantity": 5}]); page.table.selectRow(0)
    page.update("claim")
    assert api.request.call_args.args == ("POST", "/api/v1/production/tasks/7")
    assert api.request.call_args.kwargs["data"] == {"version": 1, "action": "claim"}
    page.close()


def test_operation_form_retry_keeps_idempotency_key(qt):
    api = fake_api(); page = ProductionPage(api)
    form = OperationForm(api, "Task", "/api/v1/production/tasks", page, order=True)
    form.order.addItem("Order", 123)
    form.add("title", "Title", QLineEdit("Spatha")); form.add("quantity", "Plan", amount())
    form.finish({"unit": "item"}, lambda _: None)
    form.submit()
    first = api.request.call_args.kwargs["data"]["request_key"]
    form.failure("Offline"); form.submit()
    assert api.request.call_args.kwargs["data"]["request_key"] == first
    form.failure("Offline"); form.fields["quantity"].setValue(2); form.submit()
    assert api.request.call_args.kwargs["data"]["request_key"] != first
    form.close(); page.close()
