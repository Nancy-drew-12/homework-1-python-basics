import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.account_types import SavingsAccount, PremiumAccount, InvestmentAccount
from src.exceptions import InsufficientFundsError, InvalidOperationError


def test_savings_account():
    print("=== SavingsAccount ===\n")

    acc = SavingsAccount(owner="Ольга Смирнова", currency="RUB", min_balance=1000, monthly_rate=0.02)
    acc.deposit(5000)
    print(acc)
    print()

    print("Пытаемся снять сумму, которая уведёт баланс ниже минимального остатка")
    try:
        acc.withdraw(4500)
    except InsufficientFundsError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("Снимаем допустимую сумму")
    acc.withdraw(3000)
    print(acc)
    print()

    print("Начисляем месячный процент")
    interest = acc.apply_monthly_interest()
    print(f"Начислено процентов: {interest}")
    print(acc)
    print()

    print("get_account_info():", acc.get_account_info())
    print()


def test_premium_account():
    print("=== PremiumAccount ===\n")

    acc = PremiumAccount(owner="Дмитрий Волков", currency="USD", overdraft_limit=10000, fixed_fee=300)
    acc.deposit(2000)
    print(acc)
    print()

    print("Снимаем больше, чем есть на балансе (используем овердрафт)")
    acc.withdraw(5000)
    print(acc)
    print()

    print("Пытаемся превысить лимит овердрафта")
    try:
        acc.withdraw(10000)
    except InsufficientFundsError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("get_account_info():", acc.get_account_info())
    print()


def test_investment_account():
    print("=== InvestmentAccount ===\n")

    acc = InvestmentAccount(owner="Анна Петрова", currency="RUB")
    acc.deposit(100000)
    print(acc)
    print()

    print("Инвестируем в разные активы")
    acc.invest("stocks", 40000)
    acc.invest("bonds", 30000)
    acc.invest("etf", 20000)
    print(acc)
    print()

    print("Пытаемся инвестировать в недопустимый тип актива")
    try:
        acc.invest("crypto", 1000)
    except InvalidOperationError as e:
        print(f"Корректно отклонено: {e}")
    print()

    print("Пытаемся инвестировать больше, чем есть на свободном балансе")
    try:
        acc.invest("stocks", 999999)
    except InsufficientFundsError as e:
        print(f"Корректно отклонено: {e}")
    print()

    growth_rates = {"stocks": 0.10, "bonds": 0.04, "etf": 0.07}
    projected = acc.project_yearly_growth(growth_rates)
    print(f"Ожидаемый годовой прирост портфеля при ставках {growth_rates}: {projected}")
    print()

    print("get_account_info():", acc.get_account_info())
    print()


def test_polymorphism():
    print("=== Демонстрация полиморфизма ===\n")

    accounts = [
        SavingsAccount(owner="Тест1", currency="RUB", min_balance=0),
        PremiumAccount(owner="Тест2", currency="RUB", overdraft_limit=5000),
        InvestmentAccount(owner="Тест3", currency="RUB"),
    ]

    for acc in accounts:
        acc.deposit(1000)
        print(str(acc))
        print("get_account_info:", acc.get_account_info())
        print()


def test_mentor_fixes():
    print("=== Проверка правок по ревью ===\n")

    # nan и bool в параметрах счетов
    for kwargs in [{"min_balance": float("nan")}, {"monthly_rate": True}]:
        try:
            SavingsAccount(owner="Тест", **kwargs)
            print(f"ОШИБКА: принято {kwargs}")
        except InvalidOperationError as e:
            print(f"Корректно отклонено {kwargs}: {e}")

    try:
        PremiumAccount(owner="Тест", overdraft_limit=float("nan"))
        print("ОШИБКА: принят overdraft_limit=nan")
    except InvalidOperationError as e:
        print(f"Корректно отклонено overdraft_limit=nan: {e}")

    # nan и True в операциях наследников
    inv = InvestmentAccount(owner="Тест")
    inv.deposit(1000)
    for bad in [float("nan"), True]:
        try:
            inv.invest("stocks", bad)
            print(f"ОШИБКА: invest принял {bad}")
        except InvalidOperationError as e:
            print(f"Корректно отклонено invest({bad}): {e}")

    # проценты на замороженном счёте
    sav = SavingsAccount(owner="Тест", min_balance=0)
    sav.deposit(1000)
    sav.freeze()
    try:
        sav.apply_monthly_interest()
        print("ОШИБКА: проценты начислены на замороженный счёт")
    except Exception as e:
        print(f"Корректно отклонено: {e}")

    # комиссия Premium реально списывается
    prem = PremiumAccount(owner="Тест", overdraft_limit=1000, fixed_fee=100)
    prem.deposit(1000)
    prem.withdraw(500)
    print(f"Premium: 1000 - 500 - комиссия 100 = {prem.get_account_info()['balance']} (ожидаем 400.0)")


if __name__ == "__main__":
    test_savings_account()
    test_premium_account()
    test_investment_account()
    test_polymorphism()
    test_mentor_fixes()