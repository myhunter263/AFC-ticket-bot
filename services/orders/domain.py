from enum import StrEnum


class Status(StrEnum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    WAITING_RESOURCES = "WAITING_RESOURCES"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    IN_DELIVERY = "IN_DELIVERY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    ON_HOLD = "ON_HOLD"


LABELS = dict(zip(Status, (
    "Новый", "Принят", "Ожидает ресурсов", "В производстве", "Готов",
    "Доставляется", "Выполнен", "Отменён", "Отклонён", "Приостановлен",
)))
TERMINAL = {Status.COMPLETED, Status.CANCELLED, Status.REJECTED}
TRANSITIONS = {
    Status.NEW: {Status.ACCEPTED, Status.CANCELLED, Status.REJECTED},
    Status.ACCEPTED: {Status.WAITING_RESOURCES, Status.IN_PRODUCTION, Status.READY, Status.ON_HOLD, Status.CANCELLED},
    Status.WAITING_RESOURCES: {Status.IN_PRODUCTION, Status.READY, Status.ON_HOLD, Status.CANCELLED},
    Status.IN_PRODUCTION: {Status.WAITING_RESOURCES, Status.READY, Status.ON_HOLD, Status.CANCELLED},
    Status.READY: {Status.IN_DELIVERY, Status.COMPLETED, Status.ON_HOLD, Status.CANCELLED},
    Status.IN_DELIVERY: {Status.COMPLETED, Status.ON_HOLD, Status.CANCELLED},
    Status.ON_HOLD: {Status.ACCEPTED, Status.WAITING_RESOURCES, Status.IN_PRODUCTION, Status.READY, Status.IN_DELIVERY, Status.CANCELLED},
}
