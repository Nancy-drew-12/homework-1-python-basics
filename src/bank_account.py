import uuid

from src.abstract_account import AbstractAccount
from src.exceptions import (
    AccountFrozenError,
    AccountClosedError,
    InvalidOperationError,
    InsufficientFundsError,
)


VALID_CURRENCIES = {"RUB", "USD", "EUR", "KZT", "CNY"}


def generate_short_uuid() -> str:
    """Генерирует короткий уникальный идентификатор счёта"""
    return str(uuid.uuid4())[:8]


class BankAccount(AbstractAccount):
    """Конкретная реализация банковского счёта"""

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None):
        if not account_id:
            account_id = generate_short_uuid()

        if currency not in VALID_CURRENCIES:
            raise InvalidOperationError(
                f"Неподдерживаемая валюта: {currency}. "
                f"Допустимые: {', '.join(VALID_CURRENCIES)}"
            )

        if not owner or not isinstance(owner, str):
            raise InvalidOperationError("Имя владельца должно быть непустой строкой")

        super().__init__(account_id, owner)
        self._currency = currency

    def _check_active(self):
        """Проверка, что со счётом можно работать"""
        if self._status == "frozen":
            raise AccountFrozenError(f"Счёт {self._account_id} заморожен")
        if self._status == "closed":
            raise AccountClosedError(f"Счёт {self._account_id} закрыт")

    def deposit(self, amount: float):
        self._check_active()

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма пополнения должна быть положительным числом")

        self._balance += amount
        return self._balance

    def withdraw(self, amount: float):
        self._check_active()

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма снятия должна быть положительным числом")

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно средств. Баланс: {self._balance}, запрошено: {amount}"
            )

        self._balance -= amount
        return self._balance

    def get_account_info(self) -> dict:
        return {
            "account_id": self._account_id,
            "owner": self._owner,
            "balance": self._balance,
            "currency": self._currency,
            "status": self._status,
        }

    def freeze(self):
        """Заморозить счёт"""
        self._status = "frozen"

    def close(self):
        """Закрыть счёт"""
        self._status = "closed"

    def __str__(self):
        last_four = self._account_id[-4:]
        return (
            f"BankAccount(владелец={self._owner}, "
            f"№***{last_four}, статус={self._status}, "
            f"баланс={self._balance} {self._currency})"
        )
