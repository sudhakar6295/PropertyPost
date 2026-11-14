"""Minimal JSON logs with no request body, headers, URL, or user fields."""

import json
import logging


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "application_event"),
        }
        # Exception messages can contain SQL, user input, or other private data.
        # The exception class gives operators a useful failure category without
        # serializing traceback text, request values, or database parameters.
        exception_type = getattr(record, "exception_type", None)
        if exception_type:
            payload["exception_type"] = exception_type
        return json.dumps(payload)
