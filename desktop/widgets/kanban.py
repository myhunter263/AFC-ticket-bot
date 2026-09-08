import json

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QScrollArea, QVBoxLayout, QWidget

from desktop.models.orders import STATUSES

MIME = "application/x-afc-order"


class Column(QListWidget):
    moved = Signal(dict, str)
    opened = Signal(int)

    def __init__(self, status):
        super().__init__()
        self.status = status
        self.setMinimumWidth(230)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.itemDoubleClicked.connect(lambda item: self.opened.emit(item.data(Qt.ItemDataRole.UserRole)["id"]))

    def startDrag(self, actions):
        if self.currentItem() is None:
            return
        mime = QMimeData()
        mime.setData(MIME, json.dumps(self.currentItem().data(Qt.ItemDataRole.UserRole)).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            row = json.loads(bytes(event.mimeData().data(MIME)))
            if row["status"] != self.status:
                self.moved.emit(row, self.status)
            event.acceptProposedAction()


class Kanban(QScrollArea):
    moved = Signal(dict, str)
    opened = Signal(int)

    def __init__(self):
        super().__init__()
        body = QWidget()
        layout = QHBoxLayout(body)
        self.columns = {}
        for status, label in STATUSES.items():
            box = QVBoxLayout()
            title = QLabel(label)
            title.setObjectName("columnTitle")
            column = Column(status)
            column.moved.connect(self.moved.emit)
            column.opened.connect(self.opened.emit)
            self.columns[status] = column
            box.addWidget(title)
            box.addWidget(column)
            layout.addLayout(box)
        self.setWidget(body)
        self.setWidgetResizable(True)

    def replace(self, rows):
        for column in self.columns.values():
            column.clear()
        for row in rows:
            text = f"#{row['public_number']:06d} · {row['customer_name']}\n" + "\n".join(f"{i['name']} ×{i['quantity']}" for i in row["items"][:4])
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, row)
            self.columns[row["status"]].addItem(item)
