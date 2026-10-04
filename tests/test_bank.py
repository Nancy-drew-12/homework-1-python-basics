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

    print("=== 2. Открытие счетов (банк возвращает только номера) ===")
    acc_bank = bank.open_account("c-anna", "bank", "RUB")
    acc_save = bank.open_account("c-anna", "savings", "RUB", min_balance=1000)
    acc_prem = bank.open_account("c-boris", "premium", "USD", overdraft_limit=5000, fixed_fee=10)
    acc_inv = bank.open_account("c-boris", "investment", "RUB")
    print("Тип возвращаемого значения open_account:", type(acc_bank).__name__)

    bank.deposit(acc_bank, 20000)
    bank.deposit(acc_save, 50000)
    bank.deposit(acc_prem, 300)
    bank.deposit(acc_inv, 10000)
    bank.invest(acc_inv, "stocks", 10000)  # весь баланс уходит в портфель
    for account_id in (acc_bank, acc_save, acc_prem, acc_inv):
        print(bank.describe_account(account_id))
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
    bank.freeze_account(acc_bank)
    print(bank.describe_account(acc_bank))
    try:
        bank.deposit(acc_bank, 100)
    except AccountFrozenError as e:
        print(f"Операция по замороженному счёту: {e}")
    bank.unfreeze_account(acc_bank)
    bank.deposit(acc_bank, 100)
    print(bank.describe_account(acc_bank))
    print()

    print("=== 5. Закрытие счёта ===")
    try:
        bank.close_account(acc_bank)
    except InvalidOperationError as e:
        print(f"Закрытие счёта с остатком: {e}")

    inv_info = bank.get_account_info(acc_inv)
    print(f"Инвестсчёт: свободный баланс {inv_info['balance']}, полная стоимость {inv_info['total_value']}")
    try:
        bank.close_account(acc_inv)
    except InvalidOperationError as e:
        print(f"Закрытие инвестсчёта с активами в портфеле: {e}")

    empty = bank.open_account("c-anna", "bank", "EUR")
    bank.close_account(empty)
    print(bank.describe_account(empty))
    print()

    print("=== 6. Ночной запрет (03:30): все пути через банк ===")
    clock.now = datetime(2026, 10, 4, 3, 30)
    balance_before = bank.get_account_info(acc_bank)["balance"]
    attempts = [
        ("open_account", lambda: bank.open_account("c-anna", "bank")),
        ("deposit", lambda: bank.deposit(acc_bank, 100)),
        ("withdraw", lambda: bank.withdraw(acc_bank, 100)),
        ("invest", lambda: bank.invest(acc_inv, "bonds", 1)),
        ("apply_monthly_interest", lambda: bank.apply_monthly_interest(acc_save)),
    ]
    for name, action in attempts:
        try:
            action()
            print(f"ОШИБКА: {name} прошла ночью!")
        except NightOperationError as e:
            print(f"{name}: {e}")
    balance_after = bank.get_account_info(acc_bank)["balance"]
    print(f"Баланс не изменился: {balance_before} -> {balance_after}")

    clock.now = datetime(2026, 10, 4, 5, 0)
    bank.withdraw(acc_bank, 100)
    print("В 05:00 операции уже разрешены")
    print()

    print("=== 7. Поиск счетов (возвращает копии данных) ===")
    print("Счета Анны:", len(bank.search_accounts(client_id="c-anna")))
    print("Сберегательные:", [a["account_id"] for a in bank.search_accounts(account_type="savings")])
    print("В USD:", len(bank.search_accounts(currency="USD")))
    print("Закрытые:", len(bank.search_accounts(status="closed")))
    print("Владелец содержит 'орлов':", len(bank.search_accounts(owner="орлов")))

    copy = bank.search_accounts(account_type="savings")[0]
    copy["balance"] = 999999
    print("Правка копии не влияет на счёт:", bank.get_account_info(acc_save)["balance"])
    print()

    print("=== 8. Баланс и рейтинг (портфель учитывается) ===")
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