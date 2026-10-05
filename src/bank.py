from datetime import datetime

from src.account_types import SavingsAccount, PremiumAccount, InvestmentAccount
from src.audit import AuditLog, Severity
from src.audit_reports import AuditReports
from src.bank_account import BankAccount, VALID_CURRENCIES
from src.client import Client
from src.currency import convert
from src.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotFoundError,
    AuthenticationError,
    ClientBlockedError,
    ClientNotFoundError,
    InvalidOperationError,
    NightOperationError,
    RiskBlockedError,
)
from src.risk import RiskAnalyzer


class Bank:
    """Управляющий класс банка: клиенты, счета, безопасность, аудит и риск-анализ.

    Объекты счетов наружу не выдаются: все операции идут через методы банка,
    поэтому проверка времени, аудит и риск-анализ не обходятся.
    """

    MAX_FAILED_ATTEMPTS = 3
    NIGHT_START_HOUR = 0   # операции запрещены с 00:00
    NIGHT_END_HOUR = 5     # ... до 05:00

    ACCOUNT_TYPES = {
        "bank": BankAccount,
        "savings": SavingsAccount,
        "premium": PremiumAccount,
        "investment": InvestmentAccount,
    }

    def __init__(self, name: str, clock=None, audit: AuditLog = None,
                 risk_analyzer: RiskAnalyzer = None):
        if not isinstance(name, str) or not name.strip():
            raise InvalidOperationError("Название банка должно быть непустой строкой")
        self._name = name
        self._clock = clock or datetime.now  # clock можно подменить в тестах
        self._audit = audit if audit is not None else AuditLog(clock=self._clock)
        self._risk = risk_analyzer if risk_analyzer is not None else RiskAnalyzer()
        self._clients = {}         # client_id -> Client
        self._accounts = {}        # account_id -> счёт
        self._account_owner = {}   # account_id -> client_id
        self._suspicious = []      # журнал подозрительных действий
        self._ledger = []          # журнал движения денег по счетам (для отчётов и графиков)

    # ---------- свойства ----------

    @property
    def name(self) -> str:
        return self._name

    @property
    def audit(self) -> AuditLog:
        return self._audit

    @property
    def risk_analyzer(self) -> RiskAnalyzer:
        return self._risk

    def audit_reports(self) -> AuditReports:
        return AuditReports(self._audit, self._risk)

    # ---------- время ----------

    def now(self):
        """Текущее время банка (с учётом подменённых часов в тестах)"""
        return self._clock()

    def is_night_now(self) -> bool:
        return self.NIGHT_START_HOUR <= self._clock().hour < self.NIGHT_END_HOUR

    def next_operating_time(self):
        """Ближайший момент, когда операции разрешены"""
        now = self._clock()
        if self.is_night_now():
            return now.replace(hour=self.NIGHT_END_HOUR, minute=0, second=0, microsecond=0)
        return now

    # ---------- служебные методы ----------

    def _flag_suspicious(self, client_id, reason: str):
        self._suspicious.append({
            "time": self._clock(),
            "client_id": client_id,
            "reason": reason,
        })
        self._audit.log(Severity.WARNING, "suspicious", reason, client_id=client_id)

    def _check_operating_hours(self, client_id, action: str):
        if self.is_night_now():
            now = self._clock()
            self._risk.record_night_attempt(client_id, now, action)
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
        """Любая операция со счётом сначала проходит проверку времени"""
        self._check_operating_hours(self._account_owner.get(account_id), action)
        return self._get_account(account_id)

    def owner_of(self, account_id: str):
        """ID клиента-владельца счёта (или None, если счёта нет)"""
        return self._account_owner.get(account_id)

    # ---------- журнал движения денег ----------

    def _log_change(self, account_id: str, kind: str, value_before: float):
        """Записывает изменение полной стоимости счёта (нулевые изменения не пишем)"""
        account = self._accounts[account_id]
        info = account.get_account_info()
        after = account.total_value()
        delta = round(after - value_before, 2)
        if delta == 0:
            return
        self._ledger.append({
            "time": self._clock(),
            "account_id": account_id,
            "client_id": self._account_owner.get(account_id),
            "currency": info["currency"],
            "kind": kind,
            "delta": delta,
            "balance_after": round(after, 2),
        })

    def get_ledger(self, client_id: str = None, account_id: str = None) -> list:
        """Копии записей журнала движения денег (по времени), можно фильтровать"""
        return [dict(e) for e in self._ledger
                if (client_id is None or e["client_id"] == client_id)
                and (account_id is None or e["account_id"] == account_id)]

    # ---------- клиенты ----------

    def get_client_info(self, client_id: str) -> dict:
        """Данные клиента без пароля (копия)"""
        client = self._get_client(client_id)
        return {
            "client_id": client.client_id,
            "full_name": client.full_name,
            "status": client.status,
            "account_ids": list(client.account_ids),
        }

    def list_clients(self) -> list:
        return [self.get_client_info(cid) for cid in self._clients]

    def add_client(self, client: Client) -> str:
        if not isinstance(client, Client):
            raise InvalidOperationError("add_client принимает объект Client")
        self._check_operating_hours(client.client_id, "add_client")
        if client.client_id in self._clients:
            raise InvalidOperationError(f"Клиент {client.client_id} уже существует")
        self._clients[client.client_id] = client
        self._audit.log(Severity.INFO, "client_added", f"Добавлен клиент {client.full_name}",
                        client_id=client.client_id)
        return client.client_id

    def unblock_client(self, client_id: str):
        self._check_operating_hours(client_id, "unblock_client")
        self._get_client(client_id).unblock()
        self._audit.log(Severity.INFO, "client_unblocked", "Клиент разблокирован", client_id=client_id)

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
            self._audit.log(Severity.ERROR, "client_blocked", "Клиент заблокирован",
                            client_id=client_id, error_type="ClientBlockedError")
            raise ClientBlockedError(
                f"Клиент {client_id} заблокирован: {self.MAX_FAILED_ATTEMPTS} неверные попытки входа"
            )
        raise AuthenticationError(
            f"Неверный пароль. Осталось попыток: {self.MAX_FAILED_ATTEMPTS - attempts}"
        )

    # ---------- счета: открытие и статусы ----------

    def open_account(self, client_id: str, account_type: str = "bank",
                     currency: str = "RUB", **options) -> str:
        """Открывает счёт и возвращает его номер (сам объект счёта наружу не выдаётся)"""
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
        self._risk.register_known(client_id, f"acc:{account_id}")  # свои счета - не "новые"
        self._audit.log(Severity.INFO, "account_opened", f"Открыт счёт {account_id} ({account_type}, {currency})",
                        client_id=client_id, account_id=account_id)
        return account_id

    def close_account(self, account_id: str):
        account = self._account_for_operation(account_id, "close_account")
        value = account.total_value()
        if value != 0:
            raise InvalidOperationError(
                f"Закрыть можно только счёт с нулевой стоимостью "
                f"(баланс + портфель), сейчас: {value}"
            )
        account.close()

    def freeze_account(self, account_id: str):
        self._account_for_operation(account_id, "freeze_account").freeze()

    def unfreeze_account(self, account_id: str):
        self._account_for_operation(account_id, "unfreeze_account").unfreeze()

    # ---------- счета: денежные операции (только через банк) ----------

    def deposit(self, account_id: str, amount: float):
        account = self._account_for_operation(account_id, "deposit")
        before = account.total_value()
        result = account.deposit(amount)
        self._log_change(account_id, "deposit", before)
        return result

    def withdraw(self, account_id: str, amount: float):
        account = self._account_for_operation(account_id, "withdraw")
        before = account.total_value()
        result = account.withdraw(amount)
        self._log_change(account_id, "withdraw", before)
        return result

    def invest(self, account_id: str, asset_type: str, amount: float):
        account = self._account_for_operation(account_id, "invest")
        if not isinstance(account, InvestmentAccount):
            raise InvalidOperationError("Инвестировать можно только с инвестиционного счёта")
        return account.invest(asset_type, amount)

    def apply_monthly_interest(self, account_id: str):
        account = self._account_for_operation(account_id, "apply_monthly_interest")
        if not isinstance(account, SavingsAccount):
            raise InvalidOperationError("Проценты начисляются только на сберегательном счёте")
        before = account.total_value()
        result = account.apply_monthly_interest()
        self._log_change(account_id, "interest", before)
        return result

    # ---------- проведение транзакций (с риск-анализом и откатом) ----------

    def settle(self, kind: str, amount: float, currency: str, sender_id: str = None,
               debit: float = None, recipient_id: str = None, credit: float = None,
               external_recipient: str = None, fee: float = 0.0):
        """Проводит одну операцию целиком.

        amount/currency - сумма в валюте транзакции (для оценки риска),
        debit - сколько списать со счёта отправителя (в его валюте, с комиссией),
        credit - сколько зачислить получателю (в его валюте).
        Порядок: ночь -> счета и статусы -> риск (high блокируется) -> движение денег
        с откатом при ошибке -> аудит.
        """
        actor = self._account_owner.get(sender_id) or self._account_owner.get(recipient_id)
        self._check_operating_hours(actor, kind)

        sender = self._get_account(sender_id) if sender_id else None
        recipient = self._get_account(recipient_id) if recipient_id else None
        for acc, role in ((sender, "отправителя"), (recipient, "получателя")):
            if acc is None:
                continue
            status = acc.get_account_info()["status"]
            if status == "frozen":
                raise AccountFrozenError(
                    f"Счёт {role} {acc.get_account_info()['account_id']} заморожен: операции запрещены")
            if status == "closed":
                raise AccountClosedError(
                    f"Счёт {role} {acc.get_account_info()['account_id']} закрыт: операции запрещены")

        # --- риск-анализ ---
        recipient_key = None
        if kind in ("internal_transfer", "external_transfer"):
            recipient_key = f"acc:{recipient_id}" if recipient_id else f"ext:{external_recipient}"
        amount_rub = convert(amount, currency, "RUB")
        assessment = self._risk.evaluate(actor, amount_rub, self._clock(), recipient_key)
        if assessment.blocked:
            self._flag_suspicious(actor, f"Заблокирована операция {kind}: {assessment.reasons()}")
            self._audit.log(Severity.CRITICAL, "risk_blocked",
                            f"Операция {kind} на {amount} {currency} заблокирована (риск {assessment.score}): "
                            f"{assessment.reasons()}",
                            client_id=actor, error_type="RiskBlockedError", score=assessment.score)
            raise RiskBlockedError(
                f"Операция заблокирована: высокий риск ({assessment.score} баллов): {assessment.reasons()}")
        if assessment.level.value == "medium":
            self._audit.log(Severity.WARNING, "risk_warning",
                            f"Операция {kind} на {amount} {currency}, средний риск ({assessment.score}): "
                            f"{assessment.reasons()}", client_id=actor, score=assessment.score)

        # --- движение денег с откатом ---
        snapshot = [(a, a._balance) for a in (sender, recipient) if a is not None]
        sender_before = sender.total_value() if sender is not None else None
        recipient_before = recipient.total_value() if recipient is not None else None
        try:
            if sender is not None:
                sender.withdraw(debit)
            if recipient is not None:
                recipient.deposit(credit)
        except Exception:
            for acc, balance in snapshot:
                acc._balance = balance
            raise

        if sender is not None:
            self._log_change(sender_id, f"{kind}_out", sender_before)
        if recipient is not None:
            self._log_change(recipient_id, f"{kind}_in", recipient_before)
        if recipient_key is not None:
            self._risk.confirm(actor, recipient_key)  # после успешного перевода получатель известен
        self._audit.log(Severity.INFO, "settled", f"Проведена операция {kind}: {amount} {currency}",
                        client_id=actor, kind=kind, fee=fee)
        return assessment

    # ---------- счета: чтение и поиск ----------

    def get_account_info(self, account_id: str) -> dict:
        """Копия данных счёта (изменение словаря на счёт не влияет)"""
        return self._get_account(account_id).get_account_info()

    def describe_account(self, account_id: str) -> str:
        return str(self._get_account(account_id))

    def search_accounts(self, *, client_id: str = None, owner: str = None,
                        account_type: str = None, status: str = None,
                        currency: str = None) -> list:
        """Все фильтры применяются вместе (логическое И). Возвращает копии данных"""
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
            result.append(info)
        return result

    # ---------- аналитика ----------

    def get_total_balance(self, currency: str = None):
        """Считает полную стоимость счетов (баланс + портфель).
        Без currency - словарь {валюта: сумма}, с currency - число"""
        if currency is not None and currency not in VALID_CURRENCIES:
            raise InvalidOperationError(f"Неподдерживаемая валюта: {currency}")

        totals = {}
        for account in self._accounts.values():
            cur = account.get_account_info()["currency"]
            totals[cur] = totals.get(cur, 0.0) + account.total_value()

        if currency is None:
            return totals
        return totals.get(currency, 0.0)

    def get_clients_ranking(self, currency: str = "RUB") -> list:
        """Клиенты по убыванию суммарной стоимости счетов в выбранной валюте"""
        if currency not in VALID_CURRENCIES:
            raise InvalidOperationError(f"Неподдерживаемая валюта: {currency}")

        ranking = []
        for client in self._clients.values():
            total = 0.0
            for account_id in client.account_ids:
                account = self._accounts[account_id]
                if account.get_account_info()["currency"] == currency:
                    total += account.total_value()
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