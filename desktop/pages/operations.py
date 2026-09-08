"""Warehouse and production UI. All validation and mutations go through the API."""
import uuid

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QLineEdit, QPushButton, QSpinBox, QTableView, QTabWidget, QVBoxLayout, QWidget)

LABELS = {"item": "шт.", "crate": "ящ.", "batch": "партий", "ACTIVE": "Активен",
    "RELEASED": "Освобождён", "CONSUMED": "Списан", "PLANNED": "Запланировано",
    "IN_PROGRESS": "В работе", "COMPLETED": "Выполнено", "CANCELLED": "Отменено"}


class RecordsModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent)
        self.columns, self.rows = columns, []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and role == Qt.ItemDataRole.DisplayRole:
            value = self.rows[index.row()].get(self.columns[index.column()][0])
            return str(LABELS.get(value, value) if value is not None else "—")

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.columns[section][1]

    def replace(self, rows):
        self.beginResetModel()
        self.rows = [{**r, "progress": f"{r.get('completed', 0)} / {r.get('quantity', 0)}"} for r in rows]
        self.endResetModel()


class OperationForm(QDialog):
    def __init__(self, api, title, path, parent, *, order=False, catalog=False):
        super().__init__(parent)
        self.api, self.path = api, path
        self.setWindowTitle(title); self.setMinimumWidth(480)
        self.form = QFormLayout(self)
        self.fields = {}
        self.old_payload = None
        self.key = str(uuid.uuid4())
        self.order = self.selector("Заказ", "/api/v1/orders", "public_number") if order else None
        self.item = self.selector("Предмет", "/api/v1/catalog", "name") if catalog else None
        self.notice = QLabel(); self.notice.setWordWrap(True)
        self.button = QPushButton("Сохранить"); self.button.clicked.connect(self.submit)
        self.saved = lambda _: None

    def selector(self, label, path, name):
        body = QWidget(); layout = QHBoxLayout(body)
        search = QLineEdit(placeholderText="Поиск по номеру / предмету" if name == "public_number" else "Название или алиас")
        combo = QComboBox(); combo.setMinimumContentsLength(18)
        find = QPushButton("Найти")
        def loaded(rows):
            combo.clear()
            for row in rows:
                if name == "public_number" and row["status"] in ("COMPLETED", "CANCELLED", "REJECTED"):
                    continue
                text = f"#{row[name]:06d} · {row['customer_name']}" if name == "public_number" else row[name]
                combo.addItem(text, row["id"])
        def fetch():
            self.api.request("GET", path, params={"search": search.text(), "limit": 200}, callback=loaded)
        find.clicked.connect(fetch); search.returnPressed.connect(fetch)
        layout.addWidget(search); layout.addWidget(find)
        self.form.addRow(label, body); self.form.addRow(combo)
        fetch()
        return combo

    def add(self, key, label, widget):
        self.fields[key] = widget; self.form.addRow(label, widget)

    def finish(self, extra, saved):
        self.extra, self.saved = extra, saved
        self.form.addRow(self.notice); self.form.addRow(self.button)
        self.open()

    def submit(self):
        data = dict(self.extra)
        for key, widget in self.fields.items():
            data[key] = widget.value() if isinstance(widget, QSpinBox) else widget.currentData() if isinstance(widget, QComboBox) else widget.text()
        if self.order is not None: data["order_id"] = self.order.currentData()
        if self.item is not None: data["item_id"] = self.item.currentData()
        if self.order is not None:
            if data != self.old_payload:
                self.key = str(uuid.uuid4()); self.old_payload = dict(data)
            data["request_key"] = self.key
        self.button.setEnabled(False)
        self.api.request("POST", self.path, data=data, callback=self.success, failed=self.failure)

    def success(self, row):
        self.saved(row); self.accept()

    def failure(self, text):
        self.notice.setText(text); self.button.setEnabled(True)


def amount(maximum=1000000):
    widget = QSpinBox(); widget.setRange(1, maximum)
    return widget


def units(batch=False):
    widget = QComboBox()
    for key in (("item", "crate", "batch") if batch else ("item", "crate")):
        widget.addItem(LABELS[key], key)
    return widget


class Listing(QWidget):
    def __init__(self, api, path, columns, parent=None):
        super().__init__(parent)
        self.api, self.path = api, path
        self.offset, self.params = 0, {}
        self.layout = QVBoxLayout(self)
        self.filters = QHBoxLayout(); self.layout.addLayout(self.filters)
        self.model = RecordsModel(columns, self)
        self.table = QTableView(); self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.layout.addWidget(self.table)
        self.actions = QHBoxLayout(); self.layout.addLayout(self.actions)
        nav = QHBoxLayout()
        for title, step in (("← Назад", -1), ("Далее →", 1)):
            button = QPushButton(title); button.clicked.connect(lambda checked=False, step=step: self.page(step)); nav.addWidget(button)
        self.count = QLabel(); nav.addWidget(self.count)
        self.layout.addLayout(nav)

    def page(self, step):
        self.offset = max(0, self.offset + 100 * step); self.refresh()

    def refresh(self):
        self.api.request("GET", self.path, params={**self.params, "offset": self.offset, "limit": 100}, callback=self.loaded)

    def loaded(self, rows):
        self.model.replace(rows); self.count.setText(f"Страница {self.offset // 100 + 1} · {len(rows)} записей")

    def selected(self):
        index = self.table.currentIndex()
        if index.isValid(): return self.model.rows[index.row()]
        self.api.error.emit("Выберите строку")

    def button(self, label, action):
        button = QPushButton(label); button.clicked.connect(action); self.actions.addWidget(button)
        return button

    def failed(self, message):
        self.api.error.emit(message); self.refresh()


class InventoryPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)
        self.stock = Listing(api, "/api/v1/inventory/stock", [("name", "Предмет"), ("unit", "Единица"), ("actual", "Фактически"), ("reserved", "Резерв"), ("available", "Доступно")])
        self.reservations = Listing(api, "/api/v1/inventory/reservations", [("id", "Резерв"), ("order_id", "ID заказа"), ("warehouse", "Склад"), ("name", "Предмет"), ("quantity", "Количество"), ("unit", "Единица"), ("state", "Состояние")])
        self.warehouses = QComboBox(); self.warehouses.setMinimumWidth(250)
        self.warehouses.currentIndexChanged.connect(self.filter_stock)
        self.search = QLineEdit(placeholderText="Поиск остатка")
        search = QPushButton("Найти"); search.clicked.connect(self.filter_stock)
        for w in (self.warehouses, self.search, search): self.stock.filters.addWidget(w)
        self.order_id = QLineEdit(placeholderText="ID заказа (необязательно)")
        self.state = QComboBox(); self.state.addItem("Активные", "ACTIVE"); self.state.addItem("Все резервы", "")
        apply = QPushButton("Найти"); apply.clicked.connect(self.filter_reservations)
        for w in (self.order_id, self.state, apply): self.reservations.filters.addWidget(w)
        self.stock.button("Добавить склад", self.create_warehouse)
        self.stock.button("Добавить предмет", self.create_stock)
        self.stock.button("Указать фактический остаток", self.adjust)
        self.stock.button("Зарезервировать", self.reserve)
        self.reservations.button("Освободить резерв", lambda: self.finish_reservation("release"))
        self.reservations.button("Списать со склада", lambda: self.finish_reservation("consume"))
        tabs = QTabWidget(); tabs.addTab(self.stock, "Остатки"); tabs.addTab(self.reservations, "Резервы")
        layout.addWidget(tabs)
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.refresh)

    def on_event(self, event):
        if event["type"].startswith("inventory."): self.timer.start(150)

    def refresh(self):
        self.api.request("GET", "/api/v1/inventory/warehouses", callback=self.warehouses_loaded)
        self.filter_reservations(reset=False)

    def warehouses_loaded(self, rows):
        old = self.warehouses.currentData()
        self.warehouses.blockSignals(True); self.warehouses.clear()
        for row in rows: self.warehouses.addItem(row["name"], row["id"])
        self.warehouses.setCurrentIndex(max(0, self.warehouses.findData(old)))
        self.warehouses.blockSignals(False); self.filter_stock(reset=False)

    def filter_stock(self, *args, reset=True):
        if reset: self.stock.offset = 0
        self.stock.params = {"warehouse_id": self.warehouses.currentData(), "search": self.search.text()}
        self.stock.refresh()

    def filter_reservations(self, *args, reset=True):
        if reset: self.reservations.offset = 0
        self.reservations.params = {"order_id": self.order_id.text(), "state": self.state.currentData()}
        self.reservations.refresh()

    def create_warehouse(self):
        dialog = OperationForm(self.api, "Новый склад", "/api/v1/inventory/warehouses", self)
        dialog.add("name", "Название", QLineEdit()); dialog.finish({}, lambda _: self.refresh())

    def create_stock(self):
        if not self.warehouses.currentData(): return self.api.error.emit("Сначала создайте склад")
        dialog = OperationForm(self.api, "Предмет на складе", "/api/v1/inventory/stock", self, catalog=True)
        dialog.add("unit", "Единица учёта", units())
        dialog.finish({"warehouse_id": self.warehouses.currentData()}, lambda _: self.refresh())

    def adjust(self):
        row = self.stock.selected()
        if not row: return
        value, ok = QInputDialog.getInt(self, "Фактический остаток", f"{row['name']} · {LABELS[row['unit']]}", row["actual"], 0, 100000000)
        if not ok: return
        reason, ok = QInputDialog.getText(self, "Причина корректировки", "Причина / инвентаризация")
        if ok:
            self.api.request("PATCH", f"/api/v1/inventory/stock/{row['id']}", data={"version": row["version"], "actual": value, "reason": reason}, callback=lambda _: self.refresh(), failed=self.stock.failed)

    def reserve(self):
        row = self.stock.selected()
        if not row: return
        dialog = OperationForm(self.api, f"Резерв: {row['name']} · {LABELS[row['unit']]}", "/api/v1/inventory/reservations", self, order=True)
        dialog.add("quantity", f"Количество (доступно {row['available']})", amount(100000000))
        dialog.finish({"stock_id": row["id"]}, lambda _: self.refresh())

    def finish_reservation(self, action):
        row = self.reservations.selected()
        if row:
            self.api.request("POST", f"/api/v1/inventory/reservations/{row['id']}", data={"version": row["version"], "action": action}, callback=lambda _: self.refresh(), failed=self.reservations.failed)


class ProductionPage(Listing):
    def __init__(self, api):
        super().__init__(api, "/api/v1/production/tasks", [("id", "Задача"), ("order_id", "ID заказа"), ("title", "Производство"), ("progress", "Готовность"), ("unit", "Единица"), ("assigned_user_id", "Ответственный"), ("status", "Статус")])
        self.order = QLineEdit(placeholderText="ID заказа")
        self.assigned = QLineEdit(placeholderText="ID ответственного")
        self.status = QComboBox(); self.status.addItem("Все статусы", "")
        for key in ("PLANNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"): self.status.addItem(LABELS[key], key)
        find = QPushButton("Найти"); find.clicked.connect(self.filter)
        for w in (self.order, self.assigned, self.status, find): self.filters.addWidget(w)
        self.button("Создать задачу", self.create)
        self.button("Принять", lambda: self.update("claim"))
        self.button("Указать готовность", lambda: self.update("progress"))
        self.button("Отменить задачу", lambda: self.update("cancel"))
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.refresh)

    def on_event(self, event):
        if event["type"].startswith("production."): self.timer.start(150)

    def filter(self):
        self.offset = 0
        self.params = {"order_id": self.order.text(), "assigned_user_id": self.assigned.text(), "status": self.status.currentData()}
        self.refresh()

    def create(self):
        dialog = OperationForm(self.api, "Производственная задача", self.path, self, order=True)
        dialog.add("title", "Что произвести / этап работ", QLineEdit())
        dialog.add("quantity", "План", amount())
        dialog.add("unit", "Единица", units(batch=True))
        dialog.finish({}, lambda _: self.refresh())

    def update(self, action):
        row = self.selected()
        if not row: return
        data = {"version": row["version"], "action": action}
        if action == "progress":
            value, ok = QInputDialog.getInt(self, "Готовность", f"{row['title']} · всего {row['quantity']}", row["completed"], row["completed"], row["quantity"])
            if not ok: return
            data["completed"] = value
        self.api.request("POST", f"{self.path}/{row['id']}", data=data, callback=lambda _: self.refresh(), failed=self.failed)
