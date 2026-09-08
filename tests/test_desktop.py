"""Run with requirements-desktop.txt installed; no server or user settings needed."""
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from desktop.pages.orders import OrdersPage
from desktop.windows.main_window import MainWindow


@pytest.fixture(scope="module")
def qt():
    app = QApplication.instance() or QApplication([])
    yield app


def test_kanban_mutates_backend_before_refresh(qt):
    api = SimpleNamespace(request=Mock(), error=SimpleNamespace(emit=Mock()))
    page = OrdersPage(api)
    row = {"id": 12, "status": "NEW", "version": 3}
    page.move(row, "ACCEPTED")
    args, kwargs = api.request.call_args
    assert args == ("POST", "/api/v1/orders/12/accept")
    assert kwargs["data"] == {"version": 3}
    assert row["status"] == "NEW"
    kwargs["failed"]("Conflict")
    api.error.emit.assert_called_once_with("Conflict")
    assert api.request.call_args.args == ("GET", "/api/v1/orders")
    page.close()


def test_desktop_filters_match_backend_schema(qt):
    api = SimpleNamespace(request=Mock())
    page = OrdersPage(api)
    page.category.setCurrentIndex(page.category.findData("ammunition"))
    page.since.setText("2026-09-01")
    page.refresh()
    params = api.request.call_args.kwargs["params"]
    assert params["category"] == "ammunition"
    assert params["since"] == "2026-09-01"
    page.close()


def test_all_desktop_pages_start_without_discord_or_database(qt):
    window = MainWindow()
    assert window.stack.count() == 10
    assert window.api.token == ""
    window.show()
    qt.processEvents()
    window.close()
