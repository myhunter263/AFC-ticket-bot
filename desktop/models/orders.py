from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

STATUSES = {"NEW": "Новый", "ACCEPTED": "Принят", "WAITING_RESOURCES": "Ожидает ресурсов",
            "IN_PRODUCTION": "В производстве", "READY": "Готов", "IN_DELIVERY": "Доставляется",
            "COMPLETED": "Выполнен", "CANCELLED": "Отменён", "REJECTED": "Отклонён", "ON_HOLD": "Приостановлен"}
UNITS = {"item": "шт.", "crate": "ящ.", "batch": "партий", "request": "запросов"}


class OrderTableModel(QAbstractTableModel):
    labels = ["Номер", "Заказчик", "Состав", "Статус", "Ответственный", "Доставка"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.labels)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.labels[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        row = self.rows[index.row()]
        return [f"#{row['public_number']:06d}", row["customer_name"],
                ", ".join(f"{i['name']} ×{i['quantity']} {UNITS[i['unit']]}" for i in row["items"]),
                row["status_label"], str(row["assigned_user_id"] or "—"), row["delivery_location"]][index.column()]
