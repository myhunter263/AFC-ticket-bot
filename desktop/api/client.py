import json
from urllib.parse import urlencode

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest


class ApiClient(QObject):
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.url = ""
        self.token = ""

    def request(self, method, path, data=None, callback=None, params=None, failed=None):
        suffix = "?" + urlencode({k: v for k, v in params.items() if v not in (None, "")}) if params else ""
        request = QNetworkRequest(QUrl(self.url.rstrip("/") + path + suffix))
        request.setRawHeader(b"Authorization", f"Bearer {self.token}".encode())
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(120000)
        reply = self.manager.sendCustomRequest(request, method.encode(), json.dumps(data).encode() if data is not None else b"")

        def finished():
            try:
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
                body = bytes(reply.readAll())
                payload = json.loads(body) if body else {}
                if not 200 <= status < 300:
                    detail = payload.get("detail", "Backend недоступен")
                    message = detail if isinstance(detail, str) else "Проверьте значения полей"
                    if failed:
                        failed(message)
                    else:
                        self.error.emit(message)
                elif callback:
                    callback(payload)
            except (ValueError, TypeError):
                self.error.emit("Backend вернул некорректный ответ")
            finally:
                reply.deleteLater()
        reply.finished.connect(finished)
        return reply
