from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTextEdit, QVBoxLayout, QWidget


class CalculatorPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Производственный калькулятор"))
        self.search = QLineEdit(placeholderText="Предмет или алиас")
        find = QPushButton("Найти")
        find.clicked.connect(self.find)
        self.search.returnPressed.connect(self.find)
        line = QHBoxLayout(); line.addWidget(self.search); line.addWidget(find); layout.addLayout(line)
        self.items = QComboBox()
        self.items.currentIndexChanged.connect(self.selected)
        self.quantity = QSpinBox(); self.quantity.setRange(1, 100000)
        self.unit = QComboBox(); self.unit.addItem("Штуки", "item"); self.unit.addItem("Ящики", "crate")
        calc = QPushButton("Рассчитать")
        calc.clicked.connect(self.calculate)
        for widget in (self.items, self.quantity, self.unit, calc): layout.addWidget(widget)
        self.result = QTextEdit(readOnly=True)
        layout.addWidget(self.result)

    def find(self):
        self.api.request("GET", "/api/v1/catalog", params={"search": self.search.text(), "limit": 100}, callback=self.loaded)

    def loaded(self, rows):
        self.items.clear()
        for row in rows:
            self.items.addItem(row["name"], row)

    def selected(self):
        item = self.items.currentData()
        if item:
            self.unit.setCurrentIndex(0 if item["unit"] == "item" else 1)

    def calculate(self):
        item = self.items.currentData()
        if item:
            self.api.request("POST", "/api/v1/catalog/calculate", data={"item_id": item["id"], "quantity": self.quantity.value(), "unit": self.unit.currentData()}, callback=self.show_result)

    def show_result(self, value):
        lines = []
        for method in value["methods"]:
            lines.append(f"{method['building']} · источник {method['source']}")
            lines += [f"  {k}: {v}" for k, v in method["materials"].items()]
            lines += method["notes"]
            if method.get("base_resources"):
                lines.append("Базовые ресурсы по раскрытым цепочкам:")
                lines += [f"  {k}: {v}" for k, v in method["base_resources"].items()]
            if method.get("unresolved_resources"):
                lines += [f"  {k}: {v}" for k, v in method["unresolved_resources"].items()]
            lines.append("")
        if value["unavailable_methods"]:
            lines.append("Нет рецептов: " + ", ".join(value["unavailable_methods"]))
        self.result.setPlainText("\n".join(lines) or "В каталоге нет подходящего рецепта")
