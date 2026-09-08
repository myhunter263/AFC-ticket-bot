import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"at": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                           "logger": record.name, "message": record.getMessage()}, ensure_ascii=False)


def configure():
    for name in ("backend", "services.orders"):
        logger = logging.getLogger(name)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
