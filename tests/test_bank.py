import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bank import Bank
from src.client import Client
from src.exceptions import (
    AccountFrozenError, AuthenticationError, ClientBlockedError,
    InvalidOperationError, NightOperationError, UnderageClientError,
)


class FakeClock:
    """Управляемые часы, чтобы проверять ночной запрет"""
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


def make_client(name, birth, phone, email, client_id):
    return Client(name, birth, phone, email, password="secret123", client_id=client_id)


def main():
    clock = FakeClock(datetime(2026, 10, 3, 12, 0))
    bank = Bank("ItGrind Bank", clock=clock)

    print("=== 1. Клиенты ===")
    anna = make_client("Анна Петрова", date(1990, 5, 17), "+7 900 123-45-67", "anna@mail.ru", "c-anna")
    boris = make_client("Борис Орлов", date(1985, 1, 2), "+79001112233", "boris@mail.ru", "c-boris")
    bank.add_client(anna)
    bank.add_client(boris)
    print(anna)
    print(boris)

    try:
        Client("Игорь Юный", date(2015, 1, 1), "+79001112233", "kid@mail.ru", "secret123")
    except UnderageClientError as e:
        print(f"Несовершеннолетний отклонён: {e}")
    print()

    print("=== 2. Открытие счетов ===")
    acc_bank = bank.open_account("c-anna", "bank", "RUB")
    acc_save = bank.open_account("c-anna", "savings", "RUB", min_balance=1000)
    acc_prem = bank.open_account("c-boris", "premium", "USD", overdraft_limit=5000, fixed_fee=10)
    acc_inv = bank.open_account("c-boris", "investment", "RUB")
    acc_bank.deposit(20000)
    acc_save.deposit(50000)
    acc_prem.deposit(300)
    acc_inv.deposit(10000)
    for acc in (acc_bank, acc_save, acc_prem, acc_inv):
        print(acc)
    print()

    print("=== 3. Вход и блокировка после 3 неверных попыток ===")
    print("Верный пароль:", bank.authenticate_client("c-anna", "secret123"))
    for i in range(3):
        try:
            bank.authenticate_client("c-boris", "wrong-pass")
        except (AuthenticationError, ClientBlockedError) as e:
            print(f"Попытка {i + 1}: {type(e).__name__}: {e}")
    try:
        bank.authenticate_client("c-boris", "secret123")
    except ClientBlockedError as e:
        print(f"Даже верный пароль не пускает: {e}")
    try:
        bank.open_account("c-boris", "bank")
    except ClientBlockedError as e:
        print(f"Блокированный клиент не открывает счета: {e}")
    bank.unblock_client("c-boris")
    print("После unblock_client вход:", bank.authenticate_client("c-boris", "secret123"))
    print()

    print("=== 4. Заморозка и разморозка ===")
    bank.freeze_account(acc_bank.get_account_info()["account_id"])
    print(acc_bank)
    try:
        acc_bank.deposit(100)
    except AccountFrozenError as e:
        print(f"Операция по замороженному счёту: {e}")
    bank.unfreeze_account(acc_bank.get_account_info()["account_id"])
    acc_bank.deposit(100)
    print(acc_bank)
    print()

    print("=== 5. Закрытие счёта ===")
    try:
        bank.close_account(acc_bank.get_account_info()["account_id"])
    except InvalidOperationError as e:
        print(f"Закрытие счёта с остатком: {e}")
    empty = bank.open_account("c-anna", "bank", "EUR")
    bank.close_account(empty.get_account_info()["account_id"])
    print(empty)
    print()

    print("=== 6. Ночной запрет (03:30) ===")
    clock.now = datetime(2026, 10, 4, 3, 30)
    try:
        bank.open_account("c-anna", "bank")
    except NightOperationError as e:
        print(f"Ночью: {e}")
    clock.now = datetime(2026, 10, 4, 5, 0)
    bank.open_account("c-anna", "bank")
    print("В 05:00 операции уже разрешены")
    print()

    print("=== 7. Поиск счетов ===")
    print("Счета Анны:", len(bank.search_accounts(client_id="c-anna")))
    print("Сберегательные:", [a.get_account_info()["account_id"] for a in bank.search_accounts(account_type="savings")])
    print("В USD:", len(bank.search_accounts(currency="USD")))
    print("Закрытые:", len(bank.search_accounts(status="closed")))
    print("Владелец содержит 'орлов':", len(bank.search_accounts(owner="орлов")))
    print()

    print("=== 8. Баланс и рейтинг ===")
    print("Общий баланс по валютам:", bank.get_total_balance())
    print("Общий баланс RUB:", bank.get_total_balance("RUB"))
    for place, row in enumerate(bank.get_clients_ranking("RUB"), start=1):
        print(f"{place}. {row['full_name']}: {row['total_balance']} {row['currency']}")
    print()

    print("=== 9. Подозрительные действия ===")
    for entry in bank.get_suspicious_actions():
        print(f"{entry['time']:%Y-%m-%d %H:%M} | {entry['client_id']} | {entry['reason']}")


if __name__ == "__main__":
    main()