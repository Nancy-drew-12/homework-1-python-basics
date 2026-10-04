import sys
import os
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bank import Bank
from src.client import Client
from src.exceptions import InvalidOperationError
from src.transaction import Priority, Transaction, TransactionType as T
from src.transaction_processor import TransactionProcessor
from src.transaction_queue import TransactionQueue


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def show(tx):
    reason = tx.failure_reason or "-"
    print(f"{tx.id:<6} | {tx.type:<17} | {tx.amount:>9} {tx.currency} | комиссия {tx.fee:>6} "
          f"| {tx.status:<9} | попыток {tx.attempts} | {reason}")


def main():
    clock = FakeClock(datetime(2026, 10, 5, 12, 0))
    bank = Bank("ItGrind Bank", clock=clock)
    queue = TransactionQueue()
    processor = TransactionProcessor(bank, queue)

    bank.add_client(Client("Анна Петрова", date(1990, 5, 17), "+79001234567", "anna@mail.ru",
                           "secret123", client_id="c-anna"))
    bank.add_client(Client("Борис Орлов", date(1985, 1, 2), "+79001112233", "boris@mail.ru",
                           "secret123", client_id="c-boris"))

    a1 = bank.open_account("c-anna", "bank", "RUB")
    a_frozen = bank.open_account("c-anna", "bank", "RUB")
    a_sav = bank.open_account("c-anna", "savings", "RUB", min_balance=1000)
    b_prem = bank.open_account("c-boris", "premium", "USD", overdraft_limit=1000, fixed_fee=5)
    b_eur = bank.open_account("c-boris", "bank", "EUR")
    b_rub = bank.open_account("c-boris", "bank", "RUB")

    bank.deposit(a1, 100000)
    bank.deposit(a_frozen, 500)
    bank.deposit(a_sav, 50000)
    bank.deposit(b_prem, 100)
    bank.deposit(b_eur, 20)
    bank.freeze_account(a_frozen)

    def new(tx_id, *args, **kwargs):
        tx = Transaction(*args, transaction_id=tx_id, created_at=bank.now(), **kwargs)
        queue.add(tx)
        return tx

    print("=== 1. Создаём 10 транзакций и кладём в очередь ===")
    txs = [
        new("tx-01", T.DEPOSIT, 5000, "RUB", recipient=a1),
        new("tx-02", T.INTERNAL_TRANSFER, 2000, "RUB", sender_account_id=a1, recipient=b_rub),
        new("tx-03", T.INTERNAL_TRANSFER, 9000, "RUB", sender_account_id=a1, recipient=b_prem),
        new("tx-04", T.EXTERNAL_TRANSFER, 10000, "RUB", sender_account_id=a1,
            recipient="EXT-ACC-777", priority=Priority.HIGH),
        new("tx-05", T.WITHDRAWAL, 500, "RUB", sender_account_id=b_rub),
        new("tx-06", T.INTERNAL_TRANSFER, 100, "EUR", sender_account_id=b_eur, recipient=a1),
        new("tx-07", T.INTERNAL_TRANSFER, 500, "USD", sender_account_id=b_prem, recipient=a1),
        new("tx-08", T.INTERNAL_TRANSFER, 300, "RUB", sender_account_id=a1, recipient=a_frozen),
        new("tx-09", T.INTERNAL_TRANSFER, 3000, "RUB", sender_account_id=a_sav, recipient=b_rub,
            execute_at=clock.now + timedelta(hours=1)),
        new("tx-10", T.INTERNAL_TRANSFER, 777, "RUB", sender_account_id=a1, recipient=b_rub),
    ]
    queue.cancel("tx-10", bank.now())
    print(f"В очереди ждут выполнения: {queue.pending_count()} (tx-10 отменена)")
    print()

    print("=== 2. Первый прогон (12:00): порядок и результаты ===")
    processed = processor.process_due()
    print("Порядок выполнения:", [tx.id for tx in processed])
    for tx in txs:
        show(tx)
    print(f"Ждёт отложенных: {queue.pending_count()}")
    print()

    print("=== 3. Через час (13:00) выполняется отложенная tx-09 ===")
    clock.now = datetime(2026, 10, 5, 13, 0)
    processed = processor.process_due()
    print("Выполнено:", [tx.id for tx in processed])
    show(txs[8])
    print()

    print("=== 4. Балансы ===")
    for name, account_id in (("a1", a1), ("a_sav", a_sav), ("b_prem", b_prem),
                             ("b_eur", b_eur), ("b_rub", b_rub), ("a_frozen", a_frozen)):
        info = bank.get_account_info(account_id)
        print(f"{name:<9} {info['balance']:>10} {info['currency']}")
    print()

    print("=== 5. Ночь: повторная попытка переносит операцию на 05:00 ===")
    clock.now = datetime(2026, 10, 6, 3, 30)
    night_tx = new("tx-11", T.DEPOSIT, 1000, "RUB", recipient=b_rub)
    processor.process_due()
    print(f"В 03:30: статус {night_tx.status}, попыток {night_tx.attempts}, "
          f"следующая попытка в {night_tx.execute_at:%H:%M}")
    clock.now = datetime(2026, 10, 6, 5, 0)
    processor.process_due()
    show(night_tx)
    print()

    print("=== 6. Ночь и лимит попыток (max_attempts=1) ===")
    queue2 = TransactionQueue()
    strict = TransactionProcessor(bank, queue2, max_attempts=1)
    clock.now = datetime(2026, 10, 7, 2, 0)
    tx12 = Transaction(T.DEPOSIT, 1000, "RUB", recipient=b_rub,
                       transaction_id="tx-12", created_at=bank.now())
    queue2.add(tx12)
    strict.process_due()
    show(tx12)
    print()

    print("=== 7. Некорректные данные отклоняются ===")
    for label, factory in [
        ("сумма nan", lambda: Transaction(T.DEPOSIT, float("nan"), "RUB", recipient=a1)),
        ("сумма True", lambda: Transaction(T.DEPOSIT, True, "RUB", recipient=a1)),
        ("перевод самому себе", lambda: Transaction(T.INTERNAL_TRANSFER, 10, "RUB",
                                                    sender_account_id=a1, recipient=a1)),
    ]:
        try:
            factory()
            print(f"ОШИБКА: {label} принято")
        except InvalidOperationError as e:
            print(f"{label}: {e}")
    try:
        queue.cancel("tx-01", bank.now())
    except InvalidOperationError as e:
        print(f"Отмена выполненной: {e}")
    print()

    print("=== 8. Журнал ошибок процессора ===")
    for entry in processor.get_error_log() + strict.get_error_log():
        print(f"{entry['time']:%m-%d %H:%M} | {entry['transaction_id']} | "
              f"попытка {entry['attempt']} | {entry['error']}: {entry['message']}")


if __name__ == "__main__":
    main()