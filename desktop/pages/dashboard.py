from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget
from PySide6.QtCore import QTimer

from desktop.models.orders import STATUSES


class DashboardPage(QWidget):
    def __init__(self, api):
        super().__init__()
        self.api = api
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        title = QLabel("Логистический центр")
        title.setObjectName("pageTitle")
        self.summary = QLabel("Подключитесь к backend")
        self.summary.setWordWrap(True)
        refresh = QPushButton("Обновить состояние")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(title); layout.addWidget(self.summary); layout.addWidget(refresh); layout.addStretch()

    def refresh(self):
        self.api.request("GET", "/api/v1/dashboard", callback=self.loaded)

    def on_event(self, event):
        if event["type"].startswith(("order.", "foxholehq.")):
            self.debounce.start(200)

    def loaded(self, value):
        lines = [f"{STATUSES[k]}: {v}" for k, v in value["counts"].items()]
        lines += [f"Выполнено сегодня: {value['completed_today']}", "", "Backend: доступен", "PostgreSQL: доступна",
                  f"Последний ответ бота: {value['bot_last_seen'] or 'нет связи'}",
                  f"Каталог: {value['catalog'].get('source_version') or 'не загружен'}",
                  f"Последнее обновление: {value['catalog'].get('last_success_at') or '—'}"]
        self.summary.setText("\n".join(lines))
