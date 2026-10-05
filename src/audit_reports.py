from src.audit import Severity
from src.risk import RiskLevel


class AuditReports:
    def __init__(self, audit, risk_analyzer):
        self._audit = audit
        self._risk = risk_analyzer

    def suspicious_operations(self):
        return [{"time": r.time, "client_id": r.client_id, "level": r.level.value,
                 "score": r.score, "amount_rub": r.amount_rub, "reasons": r.reasons()}
                for r in self._risk.records() if r.level != RiskLevel.LOW]

    def client_risk_profile(self, client_id):
        profile = self._risk.profile(client_id)
        entries = self._audit.filter(client_id=client_id)
        profile["audit_entries"] = len(entries)
        profile["audit_by_severity"] = {s.name: sum(1 for e in entries if e["severity"] == s)
                                        for s in Severity}
        return profile

    def error_statistics(self):
        errors = self._audit.filter(min_severity=Severity.ERROR)
        by_event, by_type = {}, {}
        for e in errors:
            by_event[e["event"]] = by_event.get(e["event"], 0) + 1
            t = e["details"].get("error_type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        return {"total_errors": len(errors), "total_entries": len(self._audit),
                "by_event": by_event, "by_error_type": by_type}