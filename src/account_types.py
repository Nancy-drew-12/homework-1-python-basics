from src.bank_account import BankAccount
from src.exceptions import InvalidOperationError, InsufficientFundsError


class SavingsAccount(BankAccount):
    """Сберегательный счёт с минимальным остатком и процентом на доход"""

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None,
                 min_balance: float = 1000.0, monthly_rate: float = 0.01):
        super().__init__(owner=owner, currency=currency, account_id=account_id)

        if not isinstance(min_balance, (int, float)) or min_balance < 0:
            raise InvalidOperationError("Минимальный остаток должен быть неотрицательным числом")
        if not isinstance(monthly_rate, (int, float)) or monthly_rate < 0:
            raise InvalidOperationError("Месячная ставка должна быть неотрицательным числом")

        self._min_balance = min_balance
        self._monthly_rate = monthly_rate

    def withdraw(self, amount: float):
        self._check_active()

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма снятия должна быть положительным числом")

        # нельзя уйти ниже минимального остатка
        if self._balance - amount < self._min_balance:
            raise InsufficientFundsError(
                f"Нельзя снять {amount}: баланс не может быть ниже "
                f"минимального остатка {self._min_balance}"
            )

        self._balance -= amount
        return self._balance

    def apply_monthly_interest(self):
        """Начисляет процент на текущий баланс"""
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
    """Премиум-счёт с овердрафтом и увеличенными лимитами"""

    def __init__(self, owner: str, currency: str = "RUB", account_id: str = None,
                 overdraft_limit: float = 50000.0, fixed_fee: float = 500.0):
        super().__init__(owner=owner, currency=currency, account_id=account_id)

        if not isinstance(overdraft_limit, (int, float)) or overdraft_limit < 0:
            raise InvalidOperationError("Лимит овердрафта должен быть неотрицательным числом")
        if not isinstance(fixed_fee, (int, float)) or fixed_fee < 0:
            raise InvalidOperationError("Комиссия должна быть неотрицательным числом")

        self._overdraft_limit = overdraft_limit
        self._fixed_fee = fixed_fee

    def withdraw(self, amount: float):
        self._check_active()

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма снятия должна быть положительным числом")

        # можно уйти в минус, но не глубже лимита овердрафта
        if self._balance - amount < -self._overdraft_limit:
            raise InsufficientFundsError(
                f"Превышен лимит овердрафта {self._overdraft_limit}"
            )

        self._balance -= amount
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

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма снятия должна быть положительным числом")

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
                f"Допустимые: {', '.join(self.VALID_ASSET_TYPES)}"
            )

        if not isinstance(amount, (int, float)) or amount <= 0:
            raise InvalidOperationError("Сумма инвестиции должна быть положительным числом")

        if amount > self._balance:
            raise InsufficientFundsError(
                f"Недостаточно средств для инвестиции. Баланс: {self._balance}, запрошено: {amount}"
            )

        self._balance -= amount
        self._portfolio[asset_type] += amount
        return self._portfolio[asset_type]

    def project_yearly_growth(self, growth_rates: dict) -> float:
        """
        Рассчитывает ожидаемый годовой прирост портфеля.
        growth_rates: словарь {тип_актива: годовая_ставка}, например {"stocks": 0.10, "bonds": 0.04, "etf": 0.07}
        """
        if not isinstance(growth_rates, dict):
            raise InvalidOperationError("growth_rates должен быть словарём")

        total_growth = 0.0
        for asset_type, amount in self._portfolio.items():
            rate = growth_rates.get(asset_type, 0.0)
            total_growth += amount * rate

        return total_growth

    def get_account_info(self) -> dict:
        info = super().get_account_info()
        info["type"] = "investment"
        info["portfolio"] = dict(self._portfolio)
        return info

    def __str__(self):
        last_four = self._account_id[-4:]
        portfolio_str = ", ".join(f"{k}={v}" for k, v in self._portfolio.items())
        return (
            f"InvestmentAccount(владелец={self._owner}, №***{last_four}, "
            f"статус={self._status}, свободный баланс={self._balance} {self._currency}, "
            f"портфель: {portfolio_str})"
        )