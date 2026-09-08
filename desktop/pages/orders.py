from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QPushButton, QSpinBox, QTableView, QTabWidget, QTextEdit, QVBoxLayout, QWidget, QScrollArea, QCheckBox)

from desktop.models.orders import OrderTableModel, STATUSES, UNITS
from desktop.widgets.kanban import Kanban


class OrdersPage(QWidget):
    changed = Signal()

    def __init__(self, api):
        super().__init__()
        self.api = api
        self.offset = 0
        self.model = OrderTableModel(self)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Заказы"))
        filters = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Номер или предмет")
        self.status = QComboBox()
        self.status.addItem("Все статусы", "")
        for key, value in STATUSES.items():
            self.status.addItem(value, key)
        self.assigned = QLineEdit(placeholderText="ID ответственного")
        self.customer = QLineEdit(placeholderText="ID заказчика")
        for widget in (self.search, self.status, self.assigned, self.customer):
            filters.addWidget(widget)
        refresh = QPushButton("Найти")
        refresh.clicked.connect(self.reset_filter)
        self.search.returnPressed.connect(self.reset_filter)
        filters.addWidget(refresh)
        layout.addLayout(filters)
        more = QHBoxLayout()
        self.category = QComboBox()
        for key, label in [("", "Все категории"), ("vehicle", "Техника"), ("ammunition", "Боеприпасы"),
                           ("equipment", "Оружие"), ("material", "Материалы"), ("delivery", "Доставка"), ("other", "Другое")]:
            self.category.addItem(label, key)
        self.since = QLineEdit(placeholderText="С даты: ГГГГ-ММ-ДД")
        self.until = QLineEdit(placeholderText="До даты: ГГГГ-ММ-ДД (не включая)")
        for widget in (self.category, self.since, self.until): more.addWidget(widget)
        layout.addLayout(more)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda index: self.open(self.model.rows[index.row()]["id"]))
        self.kanban = Kanban()
        self.kanban.opened.connect(self.open)
        self.kanban.moved.connect(self.move)
        tabs = QTabWidget()
        tabs.addTab(self.table, "Таблица")
        tabs.addTab(self.kanban, "Kanban")
        layout.addWidget(tabs)
        nav = QHBoxLayout()
        prev, next_page = QPushButton("← Назад"), QPushButton("Далее →")
        prev.clicked.connect(lambda: self.page(-1))
        next_page.clicked.connect(lambda: self.page(1))
        self.page_label = QLabel()
        nav.addWidget(prev); nav.addWidget(self.page_label); nav.addWidget(next_page)
        layout.addLayout(nav)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.refresh)

    def on_event(self, event):
        if event["type"].startswith("order."):
            self.debounce.start(150)

    def reset_filter(self):
        self.offset = 0
        self.refresh()

    def page(self, direction):
        self.offset = max(0, self.offset + direction * 100)
        self.refresh()

    def refresh(self):
        self.api.request("GET", "/api/v1/orders", params={"search": self.search.text(), "status": self.status.currentData(),
            "assigned_user_id": self.assigned.text(), "customer_id": self.customer.text(),
            "category": self.category.currentData(), "since": self.since.text(), "until": self.until.text(),
            "offset": self.offset, "limit": 100}, callback=self.loaded)

    def loaded(self, rows):
        self.model.replace(rows)
        self.kanban.replace(rows)
        self.page_label.setText(f"Страница {self.offset // 100 + 1} · {len(rows)} заказов")

    def move(self, row, status):
        path = "accept" if row["status"] == "NEW" and status == "ACCEPTED" else "status"
        data = {"version": row["version"]}
        if path == "status":
            data["status"] = status
        self.api.request("POST", f"/api/v1/orders/{row['id']}/{path}", data=data, callback=lambda _: self.refresh(), failed=self.failed)

    def failed(self, message):
        self.api.error.emit(message)
        self.refresh()

    def open(self, order_id):
        self.api.request("GET", f"/api/v1/orders/{order_id}", callback=self.show_detail)

    def show_detail(self, row):
        dialog = OrderDialog(self.api, row, self)
        dialog.finished.connect(lambda _: self.refresh())
        dialog.open()


class OrderDialog(QDialog):
    def __init__(self, api, row, parent):
        super().__init__(parent)
        self.api, self.row = api, row
        self.setWindowTitle(f"Заказ #{row['public_number']:06d} · ID {row['id']}")
        self.resize(800, 700)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{row['customer_name']} · Discord {row['discord_user_id']}\n{row['status_label']} · ответственный {row['assigned_user_id'] or '—'}\nСоздан: {row['created_at']}"))
        self.quantities = []
        form = QFormLayout()
        for item in row["items"]:
            spin = QSpinBox(); spin.setRange(1, 100000); spin.setValue(item["quantity"])
            form.addRow(f"{item['name']} · {UNITS[item['unit']]}", spin)
            self.quantities.append(spin)
        self.location = QLineEdit(row["delivery_location"])
        self.comment = QLineEdit(row["comment"])
        form.addRow("Доставка", self.location); form.addRow("Комментарий", self.comment)
        form_body = QWidget(); form_body.setLayout(form)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(form_body); scroll.setMaximumHeight(280)
        layout.addWidget(scroll)
        actions = QHBoxLayout()
        save = QPushButton("Сохранить состав")
        save.clicked.connect(self.save)
        accept = QPushButton("Принять")
        accept.clicked.connect(lambda: self.mutate("accept", {"version": row["version"]}))
        self.status = QComboBox()
        for key, value in STATUSES.items():
            self.status.addItem(value, key)
        self.status.setCurrentIndex(list(STATUSES).index(row["status"]))
        change = QPushButton("Изменить статус")
        change.clicked.connect(self.change_status)
        for widget in (save, accept, self.status, change): actions.addWidget(widget)
        layout.addLayout(actions)
        self.admin_override = QCheckBox("Административный переход")
        self.admin_override.setEnabled(getattr(api, "role", "") == "ADMIN")
        self.reason = QLineEdit(placeholderText="Причина отмены, отклонения или административного перехода")
        layout.addWidget(self.admin_override); layout.addWidget(self.reason)
        tabs = QTabWidget()
        history = QTextEdit(readOnly=True)
        history.setPlainText("\n\n".join(self.history_text(h) for h in row.get("history", [])))
        resources = QTextEdit(readOnly=True)
        parts = []
        for item in row["items"]:
            parts.append(item["name"])
            for method in item["calculation"].get("methods", []):
                parts.append(f"  {method['building']}: " + ", ".join(f"{k}: {v}" for k, v in method["materials"].items()))
                if method.get("base_resources"):
                    parts.append("  Базовые ресурсы: " + ", ".join(f"{k}: {v}" for k, v in method["base_resources"].items()))
                if method.get("unresolved_resources"):
                    parts.append("  Уточнить цепочку: " + "; ".join(method["unresolved_resources"].values()))
            if item["calculation"].get("materials"):
                parts.append(str(item["calculation"]["materials"]))
        resources.setPlainText("\n".join(parts))
        notes = QTextEdit(readOnly=True)
        notes.setPlainText("\n\n".join(f"{n['author']} · {n['at']}\n{n['content']}" for n in row.get("notes", [])))
        tabs.addTab(resources, "Ресурсы"); tabs.addTab(history, "История"); tabs.addTab(notes, "Внутренние заметки")
        layout.addWidget(tabs)
        self.note = QLineEdit(placeholderText="Внутренняя заметка")
        note_button = QPushButton("Добавить заметку")
        note_button.clicked.connect(lambda: self.mutate("notes", {"content": self.note.text()}))
        layout.addWidget(self.note); layout.addWidget(note_button)

    def mutate(self, action, data):
        self.api.request("POST", f"/api/v1/orders/{self.row['id']}/{action}", data=data, callback=lambda _: self.accept())

    def change_status(self):
        self.mutate("status", {"version": self.row["version"], "status": self.status.currentData(),
            "reason": self.reason.text(), "admin_override": self.admin_override.isChecked()})

    @staticmethod
    def history_text(h):
        names = {"order.created": "Создан заказ", "order.assigned": "Назначен ответственный",
                 "order.status_changed": "Изменён статус", "order.updated": "Изменён состав или доставка",
                 "order.note_added": "Добавлена внутренняя заметка"}
        details = h.get("details") or {}
        text = f"{h['at']} · {h['actor']}\n{names.get(h['action'], h['action'])}"
        if details.get("status"):
            text += f": {STATUSES.get(details.get('old_status'), '—')} → {STATUSES.get(details['status'], details['status'])}"
        if details.get("reason"): text += "\n" + details["reason"]
        if details.get("before"):
            text += "\nБыло: " + ", ".join(f"{i['name']} ×{i['quantity']}" for i in details["before"]["items"])
            text += "\nСтало: " + ", ".join(f"{i.get('name') or i.get('item_id')} ×{i['quantity']}" for i in details["after"]["items"])
        return text

    def save(self):
        items = [{"item_id": i["item_id"], "name": i["name"], "category": i["category"], "quantity": spin.value(),
                  "unit": i["unit"], "comment": i["comment"], "recipe_key": i["calculation"].get("batch_recipe", {}).get("key")}
                 for i, spin in zip(self.row["items"], self.quantities)]
        self.api.request("PATCH", f"/api/v1/orders/{self.row['id']}", data={"version": self.row["version"], "items": items,
            "delivery_location": self.location.text(), "comment": self.comment.text()}, callback=lambda _: self.accept())
