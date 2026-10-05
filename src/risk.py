from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from src.exceptions import InvalidOperationError


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class RiskEvent:
    name: str
    points: int
    description: str


@dataclass
class RiskAssessment:
    client_id: str
    time: datetime
    amount_rub: float
    score: int
    level: RiskLevel
    events: list = field(default_factory=list)
    recipient: str = None

    @property
    def blocked(self):
        return self.level == RiskLevel.HIGH

    def reasons(self):
        return "; ".join(e.description for e in self.events) or "признаков риска нет"


class RiskAnalyzer:
    """Баллы: сумма >=200 000 RUB = 40, >=1 000 000 = 60, больше 8 операций за 10 минут = 30,
    новый получатель = 30, ночь = 30.  <30 low, 30-59 medium, >=60 high (блокируется)."""

    LARGE_AMOUNT = 200_000
    VERY_LARGE_AMOUNT = 1_000_000
    FREQUENT_LIMIT = 8
    FREQUENT_WINDOW = timedelta(minutes=10)
    MEDIUM_FROM = 30
    HIGH_FROM = 60

    def __init__(self):
        self._known = {}      # client_id -> {известные получатели}
        self._op_times = {}   # client_id -> [время операций]
        self._records = []

    def register_known(self, client_id, recipient_key):
        self._known.setdefault(client_id, set()).add(recipient_key)

    confirm = register_known

    def is_known(self, client_id, recipient_key):
        return recipient_key in self._known.get(client_id, set())

    @classmethod
    def level_for(cls, score):
        if score >= cls.HIGH_FROM:
            return RiskLevel.HIGH
        if score >= cls.MEDIUM_FROM:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def evaluate(self, client_id, amount_rub, now, recipient_key=None):
        if amount_rub is None or amount_rub < 0:
            raise InvalidOperationError("Сумма для оценки риска должна быть неотрицательной")
        events = []
        if amount_rub >= self.VERY_LARGE_AMOUNT:
            events.append(RiskEvent("very_large_amount", 60, f"очень крупная сумма {amount_rub:,.0f} RUB"))
        elif amount_rub >= self.LARGE_AMOUNT:
            events.append(RiskEvent("large_amount", 40, f"крупная сумма {amount_rub:,.0f} RUB"))

        times = [t for t in self._op_times.get(client_id, []) if now - t <= self.FREQUENT_WINDOW]
        times.append(now)
        self._op_times[client_id] = times
        if len(times) > self.FREQUENT_LIMIT:
            events.append(RiskEvent("frequent_ops", 30, f"{len(times)} операций за 10 минут"))

        if recipient_key is not None and not self.is_known(client_id, recipient_key):
            events.append(RiskEvent("new_recipient", 30, f"перевод новому получателю {recipient_key}"))

        score = sum(e.points for e in events)
        result = RiskAssessment(client_id, now, amount_rub, score, self.level_for(score), events, recipient_key)
        self._records.append(result)
        return result

    def record_night_attempt(self, client_id, now, action):
        event = RiskEvent("night_operation", 30, f"попытка '{action}' в ночное время")
        result = RiskAssessment(client_id, now, 0.0, 30, self.level_for(30), [event])
        self._records.append(result)
        return result

    def records(self, client_id=None, level=None):
        return [r for r in self._records
                if (client_id is None or r.client_id == client_id)
                and (level is None or r.level == level)]

    def profile(self, client_id):
        records = self.records(client_id=client_id)
        by_level = {lvl.value: 0 for lvl in RiskLevel}
        by_event = {}
        for r in records:
            by_level[r.level.value] += 1
            for e in r.events:
                by_event[e.name] = by_event.get(e.name, 0) + 1
        scores = [r.score for r in records]
        max_score = max(scores, default=0)
        return {"client_id": client_id, "operations": len(records), "by_level": by_level,
                "by_event": by_event, "max_score": max_score,
                "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
                "overall_level": self.level_for(max_score).value}