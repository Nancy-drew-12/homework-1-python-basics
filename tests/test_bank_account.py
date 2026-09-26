import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.bank_account import BankAccount
from src.exceptions import AccountFrozenError, InsufficientFundsError, InvalidOperationError


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


def test_edge_cases():
    print("\n=== Проверка edge-cases (правки по ревью ментора) ===\n")

    account = BankAccount(owner="Тест Тестов", currency="RUB")

    print("1. Пытаемся пополнить счёт значением True (bool)")
    try:
        account.deposit(True)
        print("ОШИБКА: bool был принят!")
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("2. Пытаемся пополнить счёт значением nan")
    try:
        account.deposit(float("nan"))
        print("ОШИБКА: nan был принят!")
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("3. Пытаемся пополнить счёт значением inf")
    try:
        account.deposit(float("inf"))
        print("ОШИБКА: inf был принят!")
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print(f"Баланс после всех попыток остался корректным: {account.get_account_info()['balance']}")
    print()

    print("4. Пытаемся создать счёт с account_id=123 (число, не строка)")
    try:
        bad_account = BankAccount(owner="Тест", currency="RUB", account_id=123)
        print("ОШИБКА: числовой account_id был принят!")
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("5. Пытаемся создать счёт с account_id='' (пустая строка)")
    try:
        bad_account2 = BankAccount(owner="Тест", currency="RUB", account_id="")
        print("ОШИБКА: пустая строка была принята как account_id!")
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")


if __name__ == "__main__":
    main()
    test_edge_cases()