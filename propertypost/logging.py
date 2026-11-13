"""Minimal JSON logs with no request body, headers, URL, or user fields."""

import json
import logging


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {"level": record.levelname, "logger": record.name, "event": "application_event"}
        )
