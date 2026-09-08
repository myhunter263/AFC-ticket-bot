from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QStackedWidget, QWidget)

from desktop.api.client import ApiClient
from desktop.api.websocket import EventStream
from desktop.pages.admin import CatalogAdminPage, DiscordPage, RecordsPage
from desktop.pages.calculator import CalculatorPage
from desktop.pages.dashboard import DashboardPage
from desktop.pages.orders import OrdersPage
from desktop.pages.operations import InventoryPage, ProductionPage


class LoginDialog(QDialog):
    def __init__(self, api, parent):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Подключение к Hector")
        layout = QFormLayout(self)
        previous_url = QSettings("AFC", "Logistics").value("url", "http://127.0.0.1:8000")
        self.url = QLineEdit(QSettings("Hector", "Logistics").value("url", previous_url))
        self.token = QLineEdit(); self.token.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Адрес backend", self.url); layout.addRow("Личный токен", self.token)
        self.info = QLabel("Токен остаётся только в памяти приложения")
        layout.addRow(self.info)
        button = QPushButton("Подключиться"); button.clicked.connect(self.connect); layout.addRow(button)
        self.user = None

    def connect(self):
        from urllib.parse import urlparse
        url = urlparse(self.url.text())
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
            return self.info.setText("Укажите корректный HTTP(S) адрес backend")
        if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            return self.info.setText("Для удалённого backend требуется HTTPS")
        self.api.url, self.api.token = self.url.text().rstrip("/"), self.token.text().strip()
        self.api.request("GET", "/api/v1/me", callback=self.success, failed=self.info.setText)

    def success(self, user):
        if user["role"] == "BOT":
            return self.info.setText("Используйте личный токен сотрудника")
        self.user = user
        QSettings("Hector", "Logistics").setValue("url", self.api.url)
        self.token.clear()
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hector · Логистический центр")
        self.resize(1400, 900)
        self.api = ApiClient(self)
        self.api.error.connect(lambda message: QMessageBox.warning(self, "Действие не выполнено", message))
        self.stream = EventStream(self.api, self)
        self.stream.status.connect(self.statusBar().showMessage)
        body = QWidget(); layout = QHBoxLayout(body)
        self.nav = QListWidget(); self.nav.setFixedWidth(210)
        self.stack = QStackedWidget()
        self.dashboard = DashboardPage(self.api)
        self.orders = OrdersPage(self.api)
        self.pages = [self.dashboard, self.orders, CalculatorPage(self.api), DiscordPage(self.api), CatalogAdminPage(self.api),
            RecordsPage(self.api, "/api/v1/users", [("name", "Имя"), ("user_id", "Discord ID"), ("role", "Роль"), ("revoked", "Отозван")], ("Отозвать выбранный токен", "/api/v1/users/{id}/revoke")),
            RecordsPage(self.api, "/api/v1/logs", [("at", "Время"), ("actor", "Пользователь"), ("action", "Действие"), ("target", "Объект")]),
            RecordsPage(self.api, "/api/v1/discord/jobs", [("id", "Задание"), ("kind", "Тип"), ("status", "Статус"), ("attempts", "Попытки"), ("error", "Ошибка")], ("Повторить задание", "/api/v1/discord/jobs/{id}/retry"))]
        self.nav.addItems(["Главная", "Заказы", "Калькулятор", "Discord", "FoxholeHQ и словарь", "Пользователи", "История действий", "Уведомления и ошибки"])
        for page in self.pages: self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self.select_page)
        layout.addWidget(self.nav); layout.addWidget(self.stack); self.setCentralWidget(body)
        self.stream.event.connect(self.orders.on_event)
        self.stream.event.connect(self.dashboard.on_event)
        self.user = None
        self.inventory = InventoryPage(self.api)
        self.production = ProductionPage(self.api)
        for name, page in (("Склад", self.inventory), ("Производство", self.production)):
            self.nav.addItem(name)
            self.pages.append(page)
            self.stack.addWidget(page)
            self.stream.event.connect(page.on_event)

    def login(self):
        dialog = LoginDialog(self.api, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        self.user = dialog.user
        self.api.role = self.user["role"]
        if self.user["role"] not in {"ADMIN", "MANAGER"}:
            for i in (3, 4, 5, 6, 7): self.nav.item(i).setHidden(True)
        self.setWindowTitle(f"Hector · {self.user['name']}")
        self.nav.setCurrentRow(0)
        self.stream.connect()
        return True

    def select_page(self, index):
        self.stack.setCurrentIndex(index)
        if self.user and hasattr(self.pages[index], "refresh"):
            self.pages[index].refresh()

    def closeEvent(self, event):
        self.stream.close()
        self.api.token = ""
        super().closeEvent(event)
