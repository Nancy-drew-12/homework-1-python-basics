import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bank_account import BankAccount
from src.exceptions import AccountFrozenError, InsufficientFundsError


def main():
    print("=== Демонстрация работы BankAccount ===\n")

    print("1. Создаём активный счёт")
    active_account = BankAccount(owner="Екатерина Кириллина", currency="RUB")
    print(active_account)
    print()

    print("2. Создаём счёт и замораживаем его")
    frozen_account = BankAccount(owner="Иван Иванов", currency="USD")
    frozen_account.freeze()
    print(frozen_account)
    print()

    print("3. Пытаемся пополнить замороженный счёт")
    try:
        frozen_account.deposit(100)
    except AccountFrozenError as e:
        print(f"Ошибка (ожидаемо): {e}")
    print()

    print("4. Пытаемся снять деньги с замороженного счёта")
    try:
        frozen_account.withdraw(50)
    except AccountFrozenError as e:
        print(f"Ошибка (ожидаемо): {e}")
    print()

    print("5. Валидное пополнение активного счёта")
    active_account.deposit(1000)
    print(active_account)
    print()

    print("6. Валидное снятие с активного счёта")
    active_account.withdraw(300)
    print(active_account)
    print()

    print("7. Пытаемся снять больше, чем есть на счёте")
    try:
        active_account.withdraw(10000)
    except InsufficientFundsError as e:
        print(f"Ошибка (ожидаемо): {e}")
    print()

    print("8. Информация о счёте (get_account_info)")
    print(active_account.get_account_info())


if __name__ == "__main__":
    main()
