
from PySide6.QtWidgets import (QComboBox, QFormLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)


class DiscordPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.fields = {}
        for key, label in (("panel_channel_id", "ID канала панели"), ("logistics_channel_id", "ID канала логистов"),
                           ("fallback_category_id", "ID категории приватных уведомлений"), ("panel_title", "Заголовок панели"),
                           ("panel_description", "Описание панели")):
            self.fields[key] = QLineEdit()
            form.addRow(label, self.fields[key])
        layout.addLayout(form)
        for label, action in (("Загрузить", self.refresh), ("Сохранить настройки", self.save), ("Создать / обновить панель", self.publish)):
            button = QPushButton(label); button.clicked.connect(action); layout.addWidget(button)
        self.notice = QLabel(); layout.addWidget(self.notice); layout.addStretch()
        role_form = QFormLayout()
        self.role_id = QLineEdit()
        self.role_type = QComboBox()
        for role in ("ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER"):
            self.role_type.addItem(role)
        role_form.addRow("Discord Role ID", self.role_id)
        role_form.addRow("Роль в CRM", self.role_type)
        layout.addLayout(role_form)
        role_button = QPushButton("Связать роль Discord с CRM")
        role_button.clicked.connect(self.bind_role)
        layout.addWidget(role_button)
        self.bindings = QComboBox()
        layout.addWidget(self.bindings)
        remove = QPushButton("Удалить выбранную связь роли")
        remove.clicked.connect(self.unbind_role)
        layout.addWidget(remove)

    def refresh(self):
        self.api.request("GET", "/api/v1/discord/settings", callback=self.loaded)
        self.api.request("GET", "/api/v1/permissions", callback=self.roles_loaded)

    def roles_loaded(self, rows):
        self.bindings.clear()
        for r in rows: self.bindings.addItem(f"{r['discord_role_id']} → {r['app_role']}", r["id"])

    def unbind_role(self):
        if self.bindings.currentData():
            self.api.request("DELETE", f"/api/v1/permissions/{self.bindings.currentData()}", callback=lambda _: self.refresh())

    def bind_role(self):
        if not self.role_id.text().isdigit():
            return self.api.error.emit("Введите числовой ID роли")
        self.api.request("PUT", "/api/v1/permissions", data={"discord_role_id": int(self.role_id.text()), "app_role": self.role_type.currentText()}, callback=lambda _: self.refresh())

    def loaded(self, value):
        for key, widget in self.fields.items(): widget.setText(str(value.get(key) or ""))

    def save(self):
        try:
            values = {k: int(w.text()) if k.endswith("_id") and w.text() else None if k.endswith("_id") else w.text() for k, w in self.fields.items()}
        except ValueError:
            return self.api.error.emit("ID должен быть целым числом")
        self.api.request("PUT", "/api/v1/discord/settings", data=values, callback=lambda _: self.notice.setText("Настройки сохранены"))

    def publish(self):
        self.api.request("POST", "/api/v1/discord/panel", callback=lambda value: self.notice.setText(f"Публикация в очереди, задание {value['job_id']}"))


class CatalogAdminPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for label, method, path in (("Проверить кэш", "GET", "/api/v1/catalog/status"), ("Обновить кэш", "POST", "/api/v1/catalog/refresh")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, method=method, path=path: api.request(method, path, callback=lambda value: self.refresh()))
            layout.addWidget(button)
        self.search = QLineEdit(placeholderText="Предмет для алиаса или override")
        self.items = QComboBox()
        self.items.currentIndexChanged.connect(self.load_overrides)
        find = QPushButton("Найти предмет")
        find.clicked.connect(lambda: api.request("GET", "/api/v1/catalog", params={"search": self.search.text()}, callback=self.loaded))
        for w in (self.search, find, self.items): layout.addWidget(w)
        self.alias = QLineEdit(placeholderText="Русское или жаргонное название")
        layout.addWidget(self.alias)
        for label, method in (("Добавить алиас", "POST"), ("Удалить алиас", "DELETE")):
            button = QPushButton(label); button.clicked.connect(lambda checked=False, method=method: self.alias_action(method)); layout.addWidget(button)
        form = QFormLayout()
        self.method = QLineEdit(placeholderText="Ключ рецепта")
        self.building = QLineEdit(placeholderText="Название здания")
        self.materials = QLineEdit(placeholderText="bmat=100, rmat=20")
        self.output = QLineEdit("1")
        self.unit = QComboBox(); self.unit.addItem("Штуки", "item"); self.unit.addItem("Ящики", "crate")
        for label, w in (("Рецепт", self.method), ("Здание", self.building), ("Материалы", self.materials), ("Выход партии", self.output), ("Единица выхода", self.unit)):
            form.addRow(label, w)
        layout.addLayout(form)
        save = QPushButton("Сохранить override"); save.clicked.connect(self.override); layout.addWidget(save)
        self.overrides = QComboBox()
        self.overrides.currentIndexChanged.connect(self.select_override)
        layout.addWidget(self.overrides)
        remove = QPushButton("Удалить выбранный override (вернуть исходный рецепт)")
        remove.clicked.connect(self.remove_override); layout.addWidget(remove); layout.addStretch()

    def refresh(self):
        self.api.request("GET", "/api/v1/catalog/status", callback=lambda r: self.status.setText(
            f"Версия: {r.get('source_version') or '—'}\nПредметов: {r.get('item_count', 0)}\n"
            f"Обновлено: {r.get('last_success_at') or '—'}\nОшибка: {r.get('last_error') or 'нет'}"))

    def loaded(self, rows):
        self.items.clear()
        for row in rows: self.items.addItem(row["name"], row["id"])

    def load_overrides(self):
        item_id = self.items.currentData()
        if item_id:
            self.api.request("GET", f"/api/v1/catalog/{item_id}/overrides",
                callback=lambda rows: self.overrides_loaded(rows) if self.items.currentData() == item_id else None)

    def overrides_loaded(self, rows):
        self.overrides.clear()
        for row in rows: self.overrides.addItem(row["method"], row)

    def select_override(self):
        row = self.overrides.currentData()
        if row:
            self.method.setText(row["method"]); self.building.setText(row["building"] or "")
            self.materials.setText(", ".join(f"{k}={v}" for k, v in row["materials"].items()))
            self.output.setText(str(row["output_quantity"]))
            self.unit.setCurrentIndex(self.unit.findData(row["output_unit"]))

    def remove_override(self):
        from urllib.parse import quote
        if self.items.currentData() and self.overrides.currentData():
            method = quote(self.overrides.currentData()["method"], safe="")
            self.api.request("DELETE", f"/api/v1/catalog/{self.items.currentData()}/override/{method}", callback=lambda _: self.load_overrides())

    def alias_action(self, method):
        if self.items.currentData():
            self.api.request(method, f"/api/v1/catalog/{self.items.currentData()}/aliases", data={"alias": self.alias.text()}, callback=lambda _: self.status.setText("Алиас обновлён"))

    def override(self):
        if not self.items.currentData(): return
        try:
            materials = {k.strip(): float(v) for k, v in (part.split("=", 1) for part in self.materials.text().split(","))}
            value = {"method": self.method.text(), "building": self.building.text(), "materials": materials,
                     "output_quantity": int(self.output.text()), "output_unit": self.unit.currentData()}
        except ValueError:
            return self.api.error.emit("Материалы: bmat=100, rmat=20. Выход — целое число")
        self.api.request("PUT", f"/api/v1/catalog/{self.items.currentData()}/override", data=value, callback=lambda _: self.load_overrides())


class RecordsPage(QWidget):
    def __init__(self, api, path, columns, action=None):
        super().__init__()
        self.api, self.path, self.columns, self.action = api, path, columns, action
        self.rows = []
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([label for key, label in columns])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        refresh = QPushButton("Обновить"); refresh.clicked.connect(self.refresh); layout.addWidget(refresh)
        if action:
            button = QPushButton(action[0]); button.clicked.connect(self.perform); layout.addWidget(button)

    def refresh(self):
        self.api.request("GET", self.path, callback=self.loaded)

    def loaded(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, (key, label) in enumerate(self.columns): self.table.setItem(i, j, QTableWidgetItem(str(row.get(key, "—"))))
        self.table.resizeColumnsToContents()

    def perform(self):
        index = self.table.currentRow()
        if index >= 0:
            self.api.request("POST", self.action[1].format(id=self.rows[index]["id"]), callback=lambda _: self.refresh())
