import json

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket


class EventStream(QObject):
    event = Signal(dict)
    status = Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.socket = QWebSocket(parent=self)
        self.cursor = 0
        self.enabled = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.connect)
        self.socket.connected.connect(lambda: self.socket.sendTextMessage(json.dumps({"token": api.token, "after": self.cursor})))
        self.socket.textMessageReceived.connect(self.message)
        self.socket.disconnected.connect(self.disconnected)

    def connect(self):
        self.enabled = True
        self.status.emit("Подключение к событиям…")
        url = self.api.url.rstrip("/").replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        self.socket.open(QUrl(url + "/api/v1/events"))

    def disconnected(self):
        self.status.emit("Нет связи · повторное подключение")
        if self.enabled:
            self.timer.start(5000)

    def message(self, text):
        value = json.loads(text)
        if value["type"] == "connected":
            self.status.emit("События подключены")
        if "id" in value:
            self.cursor = value["id"]
            self.event.emit(value)

    def close(self):
        self.enabled = False
        self.timer.stop()
        self.socket.close()
