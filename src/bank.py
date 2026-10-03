from datetime import datetime

from src.account_types import SavingsAccount, PremiumAccount, InvestmentAccount
from src.bank_account import BankAccount, VALID_CURRENCIES
from src.client import Client
from src.exceptions import (
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    NightOperationError,
)


class Bank:
    """Управляющий класс банка: клиенты, счета, безопасность"""

    MAX_FAILED_ATTEMPTS = 3
    NIGHT_START_HOUR = 0   # операции запрещены с 00:00
    NIGHT_END_HOUR = 5     # ... до 05:00

    ACCOUNT_TYPES = {
        "bank": BankAccount,
        "savings": SavingsAccount,
        "premium": PremiumAccount,
        "investment": InvestmentAccount,
    }

    def __init__(self, name: str, clock=None):
        if not isinstance(name, str) or not name.strip():
            raise InvalidOperationError("Название банка должно быть непустой строкой")
        self._name = name
        self._clock = clock or datetime.now  # clock можно подменить в тестах
        self._clients = {}         # client_id -> Client
        self._accounts = {}        # account_id -> счёт
        self._account_owner = {}   # account_id -> client_id
        self._suspicious = []      # журнал подозрительных действий

    # ---------- служебные методы ----------

    def _flag_suspicious(self, client_id, reason: str):
        self._suspicious.append({
            "time": self._clock(),
            "client_id": client_id,
            "reason": reason,
        })

    def _check_operating_hours(self, client_id, action: str):
        now = self._clock()
        if self.NIGHT_START_HOUR <= now.hour < self.NIGHT_END_HOUR:
            self._flag_suspicious(client_id, f"Попытка '{action}' в ночное время ({now:%H:%M})")
            raise NightOperationError(
                f"Операции запрещены с {self.NIGHT_START_HOUR:02d}:00 до {self.NIGHT_END_HOUR:02d}:00"
            )

    def _get_client(self, client_id: str) -> Client:
        client = self._clients.get(client_id)
        if client is None:
            raise ClientNotFoundError(f"Клиент {client_id} не найден")
        return client

    def _get_account(self, account_id: str):
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Счёт {account_id} не найден")
        return account

    def _account_for_operation(self, account_id: str, action: str):
        self._check_operating_hours(self._account_owner.get(account_id), action)
        return self._get_account(account_id)

    # ---------- клиенты ----------

    def add_client(self, client: Client) -> str:
        self._check_operating_hours(getattr(client, "client_id", None), "add_client")
        if not isinstance(client, Client):
            raise InvalidOperationError("add_client принимает объект Client")
        if client.client_id in self._clients:
            raise InvalidOperationError(f"Клиент {client.client_id} уже существует")
        self._clients[client.client_id] = client
        return client.client_id

    def unblock_client(self, client_id: str):
        self._check_operating_hours(client_id, "unblock_client")
        self._get_client(client_id).unblock()

    def authenticate_client(self, client_id: str, password: str) -> bool:
        self._check_operating_hours(client_id, "authenticate_client")

        client = self._clients.get(client_id)
        if client is None:
            self._flag_suspicious(client_id, "Попытка входа под несуществующим ID")
            raise ClientNotFoundError(f"Клиент {client_id} не найден")

        if client.status == "blocked":
            self._flag_suspicious(client_id, "Попытка входа заблокированного клиента")
            raise ClientBlockedError(f"Клиент {client_id} заблокирован")

        if client.check_password(password):
            client.reset_failed_attempts()
            return True

        attempts = client.register_failed_attempt()
        self._flag_suspicious(
            client_id, f"Неверный пароль (попытка {attempts} из {self.MAX_FAILED_ATTEMPTS})"
        )
        if attempts >= self.MAX_FAILED_ATTEMPTS:
            client.block()
            self._flag_suspicious(client_id, "Клиент заблокирован после неверных попыток входа")
            raise ClientBlockedError(
                f"Клиент {client_id} заблокирован: {self.MAX_FAILED_ATTEMPTS} неверные попытки входа"
            )
        raise AuthenticationError(
            f"Неверный пароль. Осталось попыток: {self.MAX_FAILED_ATTEMPTS - attempts}"
        )

    # ---------- счета ----------

    def open_account(self, client_id: str, account_type: str = "bank",
                     currency: str = "RUB", **options):
        self._check_operating_hours(client_id, "open_account")
        client = self._get_client(client_id)
        if client.status != "active":
            self._flag_suspicious(client_id, "Попытка открыть счёт заблокированным клиентом")
            raise ClientBlockedError(f"Клиент {client_id} заблокирован")

        account_class = self.ACCOUNT_TYPES.get(account_type)
        if account_class is None:
            raise InvalidOperationError(
                f"Неизвестный тип счёта: {account_type}. "
                f"Допустимые: {', '.join(self.ACCOUNT_TYPES)}"
            )

        account = account_class(owner=client.full_name, currency=currency, **options)
        account_id = account.get_account_info()["account_id"]
        if account_id in self._accounts:
            raise InvalidOperationError(f"Счёт {account_id} уже существует")

        self._accounts[account_id] = account
        self._account_owner[account_id] = client_id
        client.add_account(account_id)
        return account

    def close_account(self, account_id: str):
        account = self._account_for_operation(account_id, "close_account")
        if account.get_account_info()["balance"] != 0:
            raise InvalidOperationError("Закрыть можно только счёт с нулевым балансом")
        account.close()

    def freeze_account(self, account_id: str):
        self._account_for_operation(account_id, "freeze_account").freeze()

    def unfreeze_account(self, account_id: str):
        self._account_for_operation(account_id, "unfreeze_account").unfreeze()

    def search_accounts(self, *, client_id: str = None, owner: str = None,
                        account_type: str = None, status: str = None,
                        currency: str = None) -> list:
        """Все переданные фильтры применяются вместе (логическое И)"""
        if client_id is not None:
            self._get_client(client_id)

        result = []
        for account_id, account in self._accounts.items():
            info = account.get_account_info()
            if client_id is not None and self._account_owner[account_id] != client_id:
                continue
            if owner is not None and owner.lower() not in info["owner"].lower():
                continue
            if account_type is not None and info["type"] != account_type:
                continue
            if status is not None and info["status"] != status:
                continue
            if currency is not None and info["currency"] != currency:
                continue
            result.append(account)
        return result

    # ---------- аналитика ----------

    def get_total_balance(self, currency: str = None):
        """Без currency - словарь {валюта: сумма}, с currency - число"""
        if currency is not None and currency not in VALID_CURRENCIES:
            raise InvalidOperationError(f"Неподдерживаемая валюта: {currency}")

        totals = {}
        for account in self._accounts.values():
            info = account.get_account_info()
            totals[info["currency"]] = totals.get(info["currency"], 0.0) + info["balance"]

        if currency is None:
            return totals
        return totals.get(currency, 0.0)

    def get_clients_ranking(self, currency: str = "RUB") -> list:
        """Клиенты по убыванию суммарного баланса в выбранной валюте"""
        if currency not in VALID_CURRENCIES:
            raise InvalidOperationError(f"Неподдерживаемая валюта: {currency}")

        ranking = []
        for client in self._clients.values():
            total = 0.0
            for account_id in client.account_ids:
                info = self._accounts[account_id].get_account_info()
                if info["currency"] == currency:
                    total += info["balance"]
            ranking.append({
                "client_id": client.client_id,
                "full_name": client.full_name,
                "total_balance": total,
                "currency": currency,
            })

        ranking.sort(key=lambda row: (-row["total_balance"], row["full_name"]))
        return ranking

    def get_suspicious_actions(self) -> list:
        return [dict(entry) for entry in self._suspicious]