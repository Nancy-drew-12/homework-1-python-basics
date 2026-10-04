import math

from src.bank_account import BankAccount, is_valid_amount, is_valid_non_negative
from src.exceptions import InvalidOperationError, InsufficientFundsError


class SavingsAccount(BankAccount):
    """Сберегательный счёт с минимальным остатком и процентом на доход"""

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None,
                 min_balance: float = 1000.0, monthly_rate: float = 0.01):
        super().__init__(owner=owner, currency=currency, account_id=account_id)

        if not is_valid_non_negative(min_balance):
            raise InvalidOperationError("Минимальный остаток должен быть конечным неотрицательным числом")
        if not is_valid_non_negative(monthly_rate):
            raise InvalidOperationError("Месячная ставка должна быть конечным неотрицательным числом")

        self._min_balance = min_balance
        self._monthly_rate = monthly_rate

    def withdraw(self, amount: float):
        self._check_active()

        if not is_valid_amount(amount):
            raise InvalidOperationError("Сумма снятия должна быть конечным положительным числом")

        if self._balance - amount < self._min_balance:
            raise InsufficientFundsError(
                f"Нельзя снять {amount}: баланс не может быть ниже "
                f"минимального остатка {self._min_balance}"
            )

        self._balance -= amount
        return self._balance

    def apply_monthly_interest(self):
        """Начисляет процент на текущий баланс (только на активном счёте)"""
        self._check_active()
        interest = self._balance * self._monthly_rate
        self._balance += interest
        return interest

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info["type"] = "savings"
        info["min_balance"] = self._min_balance
        info["monthly_rate"] = self._monthly_rate
        return info

    def __str__(self):
        last_four = self._account_id[-4:]
        return (
            f"SavingsAccount(владелец={self._owner}, №***{last_four}, "
            f"статус={self._status}, баланс={self._balance} {self._currency}, "
            f"мин.остаток={self._min_balance}, ставка={self._monthly_rate * 100}%/мес)"
        )


class PremiumAccount(BankAccount):
    """Премиум-счёт с овердрафтом и фиксированной комиссией за снятие"""

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None,
                 overdraft_limit: float = 50000.0, fixed_fee: float = 500.0):
        super().__init__(owner=owner, currency=currency, account_id=account_id)

        if not is_valid_non_negative(overdraft_limit):
            raise InvalidOperationError("Лимит овердрафта должен быть конечным неотрицательным числом")
        if not is_valid_non_negative(fixed_fee):
            raise InvalidOperationError("Комиссия должна быть конечным неотрицательным числом")

        self._overdraft_limit = overdraft_limit
        self._fixed_fee = fixed_fee

    def withdraw(self, amount: float):
        """Списывает сумму + фиксированную комиссию; баланс может уйти в минус до лимита овердрафта"""
        self._check_active()

        if not is_valid_amount(amount):
            raise InvalidOperationError("Сумма снятия должна быть конечным положительным числом")

        total = amount + self._fixed_fee
        if self._balance - total < -self._overdraft_limit:
            raise InsufficientFundsError(
                f"Превышен лимит овердрафта {self._overdraft_limit} "
                f"(сумма {amount} + комиссия {self._fixed_fee})"
            )

        self._balance -= total
        return self._balance

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info["type"] = "premium"
        info["overdraft_limit"] = self._overdraft_limit
        info["fixed_fee"] = self._fixed_fee
        return info

    def __str__(self):
        last_four = self._account_id[-4:]
        return (
            f"PremiumAccount(владелец={self._owner}, №***{last_four}, "
            f"статус={self._status}, баланс={self._balance} {self._currency}, "
            f"овердрафт до {self._overdraft_limit}, комиссия={self._fixed_fee})"
        )


class InvestmentAccount(BankAccount):
    """Инвестиционный счёт с портфелем виртуальных активов"""

    VALID_ASSET_TYPES = {"stocks", "bonds", "etf"}

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None):
        super().__init__(owner=owner, currency=currency, account_id=account_id)
        self._portfolio = {asset: 0.0 for asset in self.VALID_ASSET_TYPES}

    def withdraw(self, amount: float):
        """Снятие свободных денег со счёта (не из портфеля)"""
        self._check_active()

        if not is_valid_amount(amount):
            raise InvalidOperationError("Сумма снятия должна быть конечным положительным числом")

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно свободных средств. Баланс: {self._balance}, запрошено: {amount}"
            )

        self._balance -= amount
        return self._balance

    def invest(self, asset_type: str, amount: float):
        """Переводит деньги со свободного баланса в конкретный тип актива"""
        self._check_active()

        if asset_type not in self.VALID_ASSET_TYPES:
            raise InvalidOperationError(
                f"Недопустимый тип актива: {asset_type}. "
                f"Допустимые: {', '.join(sorted(self.VALID_ASSET_TYPES))}"
            )

        if not is_valid_amount(amount):
            raise InvalidOperationError("Сумма инвестиции должна быть конечным положительным числом")

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно средств для инвестиции. Баланс: {self._balance}, запрошено: {amount}"
            )

        self._balance -= amount
        self._portfolio[asset_type] += amount
        return self._portfolio[asset_type]

    def project_yearly_growth(self, growth_rates: dict) -> float:
        """Ожидаемый годовой прирост портфеля. growth_rates: {тип_актива: годовая_ставка}"""
        if not isinstance(growth_rates, dict):
            raise InvalidOperationError("growth_rates должен быть словарём")

        for asset_type, rate in growth_rates.items():
            if asset_type not in self.VALID_ASSET_TYPES:
                raise InvalidOperationError(f"Недопустимый тип актива в ставках: {asset_type}")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate):
                raise InvalidOperationError(f"Некорректная ставка для {asset_type}: {rate}")

        total_growth = 0.0
        for asset_type, amount in self._portfolio.items():
            total_growth += amount * growth_rates.get(asset_type, 0.0)

        return total_growth

    def total_value(self) -> float:
        """Свободный баланс плюс всё, что вложено в портфель"""
        return self._balance + sum(self._portfolio.values())

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info["type"] = "investment"
        info["portfolio"] = dict(self._portfolio)
        return info

    def __str__(self):
        last_four = self._account_id[-4:]
        portfolio_str = ", ".join(f"{k}={v}" for k, v in sorted(self._portfolio.items()))
        return (
            f"InvestmentAccount(владелец={self._owner}, №***{last_four}, "
            f"статус={self._status}, свободный баланс={self._balance} {self._currency}, "
            f"портфель: {portfolio_str})"
        )