from __future__ import annotations

import logging
import sys
import uuid


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)


def new_request_id() -> str:
    return str(uuid.uuid4())


class RequestLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        rid = self.extra.get("request_id", "-")
        return f"[{rid}] {msg}", kwargs
