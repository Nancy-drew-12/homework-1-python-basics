import os
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.audit import AuditLog, Severity
from src.bank import Bank
from src.client import Client
from src.exceptions import InvalidOperationError, RiskBlockedError
from src.risk import RiskAnalyzer, RiskLevel
from src.transaction import Transaction, TransactionType as T
from src.transaction_processor import TransactionProcessor
from src.transaction_queue import TransactionQueue


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def section(title):
    print(f"\n=== {title} ===")


def show(tx):
    reason = tx.failure_reason or "-"
    print(f"{tx.id:<5} | {tx.type:<17} | {tx.amount:>9} {tx.currency} | {tx.status:<9} | {reason}")


def main():
    clock = FakeClock(datetime(2026, 10, 5, 12, 0))
    log_path = os.path.join(tempfile.mkdtemp(), "audit.log")
    bank = Bank("Тест-банк", clock=clock, audit=AuditLog(log_path, clock=clock))
    queue = TransactionQueue()
    processor = TransactionProcessor(bank, queue)

    bank.add_client(Client("Анна Петрова", date(1990, 5, 17), "+79001234567", "anna@mail.ru",
                           "secret123", client_id="c-anna"))
    bank.add_client(Client("Борис Орлов", date(1985, 1, 2), "+79001112233", "boris@mail.ru",
                           "secret123", client_id="c-boris"))
    a1 = bank.open_account("c-anna", "bank", "RUB")
    a2 = bank.open_account("c-anna", "bank", "RUB")
    b1 = bank.open_account("c-boris", "bank", "RUB")
    # крупное пополнение банк заблокировал бы как высокий риск, поэтому вносим частями и сдвигаем время
    start = clock.now
    clock.now = start - timedelta(hours=1)
    for _ in range(8):                      # 8 x 199 999 = ~1,6 млн: хватит на все сценарии
        bank.deposit(a1, 199_999)
        clock.now += timedelta(minutes=2)
    bank.deposit(b1, 100_000)
    clock.now = start

    def run(tx_id, *args, **kwargs):
        """Создаёт транзакцию, кладёт в очередь и сразу выполняет"""
        tx = Transaction(*args, transaction_id=tx_id, created_at=bank.now(), **kwargs)
        queue.add(tx)
        processor.process_due()
        return tx

    def last_risk():
        return bank.risk_analyzer.records()[-1]

    section("1. Обычные операции: низкий риск")
    tx = run("t1", T.DEPOSIT, 5_000, "RUB", recipient=a1)
    tx2 = run("t2", T.INTERNAL_TRANSFER, 10_000, "RUB", sender_account_id=a1, recipient=a2)
    show(tx)
    show(tx2)
    assert tx.status == "completed" and tx2.status == "completed"
    assert all(r.level == RiskLevel.LOW for r in bank.risk_analyzer.records())

    section("2. Перевод новому получателю: средний риск, но проходит")
    tx = run("t3", T.INTERNAL_TRANSFER, 1_000, "RUB", sender_account_id=a1, recipient=b1)
    show(tx)
    assert tx.status == "completed" and last_risk().level == RiskLevel.MEDIUM
    run("t4", T.INTERNAL_TRANSFER, 1_000, "RUB", sender_account_id=a1, recipient=b1)
    assert last_risk().level == RiskLevel.LOW
    print("Тот же получатель повторно: риск low")

    section("3. Крупные суммы: свой счёт проходит, новому получателю и 1 млн блокируются")
    tx = run("t5", T.INTERNAL_TRANSFER, 250_000, "RUB", sender_account_id=a1, recipient=a2)
    show(tx)
    assert tx.status == "completed" and last_risk().score == 40
    before = bank.get_account_info(a1)["balance"]
    tx = run("t6", T.EXTERNAL_TRANSFER, 250_000, "RUB", sender_account_id=a1, recipient="ООО Ромашка")
    show(tx)
    assert tx.status == "failed" and "высокий риск" in tx.failure_reason
    assert bank.get_account_info(a1)["balance"] == before, "деньги не должны списаться"
    tx = run("t7", T.INTERNAL_TRANSFER, 1_200_000, "RUB", sender_account_id=a1, recipient=a2)
    show(tx)
    assert tx.status == "failed"

    section("4. Частые операции: больше 8 за 10 минут")
    clock.now += timedelta(minutes=30)
    levels = []
    for i in range(10):
        run(f"f{i}", T.INTERNAL_TRANSFER, 100, "RUB", sender_account_id=a2, recipient=a1)
        levels.append(last_risk().level.value)
        clock.now += timedelta(seconds=20)
    print(levels)
    assert levels[:8] == ["low"] * 8 and levels[8] == "medium"

    section("5. Ночь: попытка фиксируется как риск, операция переносится на 05:00")
    clock.now = datetime(2026, 10, 6, 3, 30)
    tx = run("n1", T.DEPOSIT, 1_000, "RUB", recipient=a1)
    show(tx)
    assert tx.status == "pending" and tx.attempts == 1
    night = [r for r in bank.risk_analyzer.records()
             if r.events and r.events[0].name == "night_operation"]
    assert night and night[0].level == RiskLevel.MEDIUM
    clock.now = datetime(2026, 10, 6, 5, 0)
    processor.process_due()
    assert tx.status == "completed"
    print("В 05:00 операция выполнена")

    section("6. AuditLog: фильтры, память и файл совпадают")
    log = bank.audit
    file_entries = log.read_file()
    print(f"В памяти: {len(log)}, в файле: {len(file_entries)}")
    assert len(log) == len(file_entries)
    crit = log.filter(min_severity=Severity.CRITICAL)
    assert len(crit) == 2 and all(e["severity"] == Severity.CRITICAL for e in crit)
    assert all(e["client_id"] == "c-anna" for e in log.filter(client_id="c-anna"))
    assert len(log.filter(event="tx_completed")) >= 10
    window = log.filter(since=datetime(2026, 10, 6), until=datetime(2026, 10, 7))
    assert window and all(e["time"].day == 6 for e in window)
    entry = log.entries[0]
    entry["message"] = "взлом"
    assert log.entries[0]["message"] != "взлом", "наружу отдаются копии"
    try:
        log.log("INFO", "x", "y")
    except InvalidOperationError as e:
        print("Строка вместо Severity отклонена:", e)

    section("7. Отчёты аудита")
    reports = bank.audit_reports()
    print("Подозрительные операции:")
    for row in reports.suspicious_operations():
        print(f"  {row['time']:%m-%d %H:%M} | {row['client_id']} | {row['level']:<6} | "
              f"{row['score']} | {row['reasons']}")
    profile = reports.client_risk_profile("c-anna")
    print("Риск-профиль Анны:", profile)
    assert profile["by_level"]["high"] == 2 and profile["overall_level"] == "high"
    stats = reports.error_statistics()
    print("Статистика ошибок:", stats)
    assert stats["by_error_type"]["RiskBlockedError"] == 2
    boris = reports.client_risk_profile("c-boris")
    assert boris["operations"] == 1 and boris["overall_level"] == "low", "у Бориса только стартовое пополнение"

    section("8. Прямой вызов settle тоже блокируется")
    try:
        bank.settle("external_transfer", 900_000, "RUB", a1, 900_000, None, None, "Левый получатель")
        print("ОШИБКА: операция прошла")
    except RiskBlockedError as e:
        print("Корректно заблокировано:", e)

    section("9. Уровни риска по баллам")
    assert RiskAnalyzer.level_for(0) == RiskLevel.LOW
    assert RiskAnalyzer.level_for(29) == RiskLevel.LOW
    assert RiskAnalyzer.level_for(30) == RiskLevel.MEDIUM
    assert RiskAnalyzer.level_for(59) == RiskLevel.MEDIUM
    assert RiskAnalyzer.level_for(60) == RiskLevel.HIGH
    print("Границы low/medium/high верны")

    section("10. Публичные deposit, withdraw и invest тоже проходят риск и аудит")
    clock.now = datetime(2026, 10, 7, 12, 0)
    c_roman = Client("Роман Белов", date(1991, 4, 3), "+79005550000", "roman@mail.ru", "secret123", client_id="c-roman")
    bank.add_client(c_roman)
    r1 = bank.open_account("c-roman", "bank", "RUB")
    r_inv = bank.open_account("c-roman", "investment", "RUB")
    records_before = len(bank.risk_analyzer.records())
    for label, call in (("deposit 2 000 000", lambda: bank.deposit(r1, 2_000_000)),
                        ("withdraw 1 500 000", lambda: bank.withdraw(r1, 1_500_000)),
                        ("invest 1 200 000", lambda: bank.invest(r_inv, "stocks", 1_200_000))):
        try:
            call()
            raise AssertionError(f"{label}: операция прошла в обход риск-анализа")
        except RiskBlockedError as e:
            print(f"{label}: заблокировано ({e})")
    assert bank.get_account_info(r1)["balance"] == 0, "деньги не должны появиться на счёте"
    assert len(bank.risk_analyzer.records()) == records_before + 3, "каждая попытка попала в риск-оценки"
    blocked = [e for e in bank.audit.filter(client_id="c-roman") if e["event"] == "risk_blocked"]
    assert len(blocked) == 3, "в аудите три записи risk_blocked"

    bank.deposit(r1, 50_000)                  # обычная операция проходит и пишется в аудит
    assert bank.audit.filter(client_id="c-roman")[-1]["event"] == "settled"
    print("Обычное пополнение 50 000 проходит, запись в аудите есть")

    print("\nВсе проверки пройдены")


if __name__ == "__main__":
    main()