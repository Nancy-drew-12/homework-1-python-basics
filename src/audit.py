import json
from datetime import datetime
from enum import IntEnum

from src.exceptions import InvalidOperationError


class Severity(IntEnum):
    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40


class AuditLog:
    """Журнал аудита: память + файл JSON Lines. Наружу отдаются копии записей."""

    def __init__(self, file_path: str = None, clock=None):
        self._file_path = file_path
        self._clock = clock or datetime.now
        self._entries = []
        if file_path is not None:
            open(file_path, "w", encoding="utf-8").close()

    def log(self, severity, event, message, client_id=None, **details):
        if not isinstance(severity, Severity):
            raise InvalidOperationError("severity должен быть значением Severity")
        if not isinstance(event, str) or not event.strip():
            raise InvalidOperationError("Название события должно быть непустой строкой")
        entry = {"time": self._clock(), "severity": severity, "event": event,
                 "client_id": client_id, "message": message, "details": details}
        self._entries.append(entry)
        if self._file_path is not None:
            record = dict(entry, time=entry["time"].isoformat(), severity=severity.name)
            with open(self._file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return dict(entry)

    @property
    def entries(self):
        return [dict(e) for e in self._entries]

    def __len__(self):
        return len(self._entries)

    def filter(self, min_severity=None, event=None, client_id=None, since=None, until=None):
        """Все условия работают вместе (логическое И)"""
        result = []
        for e in self._entries:
            if min_severity is not None and e["severity"] < min_severity:
                continue
            if event is not None and e["event"] != event:
                continue
            if client_id is not None and e["client_id"] != client_id:
                continue
            if since is not None and e["time"] < since:
                continue
            if until is not None and e["time"] > until:
                continue
            result.append(dict(e))
        return result

    def read_file(self):
        if self._file_path is None:
            raise InvalidOperationError("Файл журнала не задан")
        with open(self._file_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]