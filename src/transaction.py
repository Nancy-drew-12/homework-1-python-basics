from datetime import datetime

from src.bank_account import (
    VALID_CURRENCIES,
    generate_short_uuid,
    is_valid_amount,
    is_valid_non_negative,
)
from src.exceptions import InvalidOperationError


class TransactionType:
    DEPOSIT = "deposit"                      # пополнение (только получатель)
    WITHDRAWAL = "withdrawal"                # снятие (только отправитель)
    INTERNAL_TRANSFER = "internal_transfer"  # перевод между счетами банка
    EXTERNAL_TRANSFER = "external_transfer"  # перевод вне банка (с комиссией)
    ALL = {DEPOSIT, WITHDRAWAL, INTERNAL_TRANSFER, EXTERNAL_TRANSFER}


class TransactionStatus:
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Priority:
    HIGH = 1
    NORMAL = 2
    LOW = 3
    ALL = {HIGH, NORMAL, LOW}


def _is_non_empty_str(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


class Transaction:
    """Транзакция: тип, сумма, валюта, комиссия, участники, статус, причина отказа, время"""

    def __init__(self, tx_type: str, amount: float, currency: str,
                 sender_account_id: str = None, recipient: str = None,
                 priority: int = Priority.NORMAL,
                 execute_at: datetime = None, created_at: datetime = None,
                 transaction_id: str = None):
        if tx_type not in TransactionType.ALL:
            raise InvalidOperationError(f"Неизвестный тип транзакции: {tx_type}")
        if not is_valid_amount(amount):
            raise InvalidOperationError("Сумма транзакции должна быть конечным положительным числом")
        if currency not in VALID_CURRENCIES:
            raise InvalidOperationError(f"Неподдерживаемая валюта: {currency}")
        if isinstance(priority, bool) or priority not in Priority.ALL:
            raise InvalidOperationError("Приоритет должен быть 1 (высокий), 2 (обычный) или 3 (низкий)")

        created_at = created_at if created_at is not None else datetime.now()
        if not isinstance(created_at, datetime):
            raise InvalidOperationError("created_at должен быть datetime")
        execute_at = execute_at if execute_at is not None else created_at
        if not isinstance(execute_at, datetime):
            raise InvalidOperationError("execute_at должен быть datetime")
        if execute_at < created_at:
            raise InvalidOperationError("Время выполнения не может быть раньше создания")

        if transaction_id is None:
            transaction_id = generate_short_uuid()
        elif not _is_non_empty_str(transaction_id):
            raise InvalidOperationError("ID транзакции должен быть непустой строкой")

        self._validate_parties(tx_type, sender_account_id, recipient)

        self._id = transaction_id
        self._type = tx_type
        self._amount = amount
        self._currency = currency
        self._fee = 0.0
        self._sender = sender_account_id
        self._recipient = recipient
        self._priority = priority
        self._status = TransactionStatus.PENDING
        self._failure_reason = None
        self._attempts = 0
        self._created_at = created_at
        self._execute_at = execute_at
        self._finished_at = None

    @staticmethod
    def _validate_parties(tx_type, sender, recipient):
        if tx_type == TransactionType.DEPOSIT:
            if sender is not None or not _is_non_empty_str(recipient):
                raise InvalidOperationError("Пополнение: нужен только получатель")
        elif tx_type == TransactionType.WITHDRAWAL:
            if recipient is not None or not _is_non_empty_str(sender):
                raise InvalidOperationError("Снятие: нужен только отправитель")
        else:
            if not _is_non_empty_str(sender) or not _is_non_empty_str(recipient):
                raise InvalidOperationError("Перевод: нужны отправитель и получатель")
            if tx_type == TransactionType.INTERNAL_TRANSFER and sender == recipient:
                raise InvalidOperationError("Нельзя переводить на тот же счёт")

    # ---------- чтение ----------

    id = property(lambda self: self._id)
    type = property(lambda self: self._type)
    amount = property(lambda self: self._amount)
    currency = property(lambda self: self._currency)
    fee = property(lambda self: self._fee)
    sender_account_id = property(lambda self: self._sender)
    recipient = property(lambda self: self._recipient)
    priority = property(lambda self: self._priority)
    status = property(lambda self: self._status)
    failure_reason = property(lambda self: self._failure_reason)
    attempts = property(lambda self: self._attempts)
    created_at = property(lambda self: self._created_at)
    execute_at = property(lambda self: self._execute_at)
    finished_at = property(lambda self: self._finished_at)

    # ---------- смена состояния (только из pending) ----------

    def _ensure_pending(self):
        if self._status != TransactionStatus.PENDING:
            raise InvalidOperationError(f"Транзакция {self._id} уже в статусе {self._status}")

    @staticmethod
    def _ensure_datetime(value):
        if not isinstance(value, datetime):
            raise InvalidOperationError("Время должно быть datetime")

    def set_fee(self, fee: float):
        self._ensure_pending()
        if not is_valid_non_negative(fee):
            raise InvalidOperationError("Комиссия должна быть конечным неотрицательным числом")
        self._fee = fee

    def register_attempt(self):
        self._ensure_pending()
        self._attempts += 1

    def reschedule(self, execute_at: datetime):
        self._ensure_pending()
        self._ensure_datetime(execute_at)
        self._execute_at = execute_at

    def mark_completed(self, when: datetime):
        self._ensure_pending()
        self._ensure_datetime(when)
        self._status = TransactionStatus.COMPLETED
        self._finished_at = when

    def mark_failed(self, reason: str, when: datetime):
        self._ensure_pending()
        self._ensure_datetime(when)
        if not _is_non_empty_str(reason):
            raise InvalidOperationError("Нужна причина отказа")
        self._status = TransactionStatus.FAILED
        self._failure_reason = reason
        self._finished_at = when

    def cancel(self, when: datetime, reason: str = "Отменена пользователем"):
        self._ensure_pending()
        self._ensure_datetime(when)
        self._status = TransactionStatus.CANCELLED
        self._failure_reason = reason
        self._finished_at = when

    def to_dict(self) -> dict:
        return {
            "id": self._id, "type": self._type, "amount": self._amount,
            "currency": self._currency, "fee": self._fee,
            "sender": self._sender, "recipient": self._recipient,
            "priority": self._priority, "status": self._status,
            "failure_reason": self._failure_reason, "attempts": self._attempts,
            "created_at": self._created_at, "execute_at": self._execute_at,
            "finished_at": self._finished_at,
        }

    def __str__(self):
        return (
            f"Transaction({self._id}, {self._type}, {self._amount} {self._currency}, "
            f"комиссия={self._fee}, статус={self._status})"
        )