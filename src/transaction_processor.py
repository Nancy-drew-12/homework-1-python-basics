from src.bank import Bank
from src.bank_account import is_valid_non_negative
from src.currency import convert
from src.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotFoundError,
    InsufficientFundsError,
    InvalidOperationError,
    NightOperationError,
    TransactionRuleError,
)
from src.transaction import Transaction, TransactionType
from src.transaction_queue import TransactionQueue


class TransactionProcessor:
    """Выполняет транзакции из очереди: комиссии, конвертация, повторы, журнал ошибок.

    Деньги двигаются только через методы Bank, поэтому ночной запрет не обходится.
    """

    EXTERNAL_FEE_RATE = 0.01  # 1% за внешний перевод
    PERMANENT_ERRORS = (
        AccountFrozenError, AccountClosedError, InsufficientFundsError,
        InvalidOperationError, AccountNotFoundError, TransactionRuleError,
    )

    def __init__(self, bank: Bank, queue: TransactionQueue,
                 max_attempts: int = 3, external_fee_rate: float = EXTERNAL_FEE_RATE):
        if not isinstance(bank, Bank) or not isinstance(queue, TransactionQueue):
            raise InvalidOperationError("Нужны объекты Bank и TransactionQueue")
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise InvalidOperationError("max_attempts должен быть целым числом >= 1")
        if not is_valid_non_negative(external_fee_rate) or external_fee_rate >= 1:
            raise InvalidOperationError("Ставка комиссии должна быть числом от 0 до 1")
        self._bank = bank
        self._queue = queue
        self._max_attempts = max_attempts
        self._fee_rate = external_fee_rate
        self._error_log = []

    # ---------- основной цикл ----------

    def process_due(self) -> list:
        """Выполняет все транзакции, время которых наступило. Возвращает обработанные"""
        processed = []
        while True:
            tx = self._queue.pop_due(self._bank.now())
            if tx is None:
                break
            self._process(tx)
            processed.append(tx)
        return processed

    def get_error_log(self) -> list:
        return [dict(entry) for entry in self._error_log]

    def _log(self, tx: Transaction, error: Exception, note: str = ""):
        self._error_log.append({
            "time": self._bank.now(),
            "transaction_id": tx.id,
            "attempt": tx.attempts,
            "error": type(error).__name__,
            "message": f"{error} {note}".strip(),
        })

    def _process(self, tx: Transaction):
        now = self._bank.now()
        tx.register_attempt()
        try:
            if self._bank.is_night_now():
                raise NightOperationError("Ночное время: операции временно недоступны")
            self._apply(tx)
        except NightOperationError as e:
            self._log(tx, e)
            if tx.attempts >= self._max_attempts:
                tx.mark_failed(f"Превышено число попыток ({tx.attempts}): {e}", now)
            else:
                tx.reschedule(self._bank.next_operating_time())
                self._queue.requeue(tx)
        except self.PERMANENT_ERRORS as e:
            self._log(tx, e)
            tx.mark_failed(str(e), now)
        except Exception as e:
            self._log(tx, e, "(непредвиденная ошибка)")
            tx.mark_failed(f"Непредвиденная ошибка: {e}", now)
            raise
        else:
            tx.mark_completed(now)

    # ---------- логика выполнения ----------

    def _calc_fee(self, tx: Transaction) -> float:
        if tx.type == TransactionType.EXTERNAL_TRANSFER:
            return round(tx.amount * self._fee_rate, 2)
        return 0.0

    def _active_info(self, account_id: str, role: str) -> dict:
        info = self._bank.get_account_info(account_id)
        if info["status"] == "frozen":
            raise AccountFrozenError(f"Счёт {role} {account_id} заморожен: операции запрещены")
        if info["status"] == "closed":
            raise AccountClosedError(f"Счёт {role} {account_id} закрыт: операции запрещены")
        return info

    def _apply(self, tx: Transaction):
        bank = self._bank
        fee = self._calc_fee(tx)

        sender = None
        recipient = None
        if tx.sender_account_id is not None:
            sender = self._active_info(tx.sender_account_id, "отправителя")
        if tx.type in (TransactionType.DEPOSIT, TransactionType.INTERNAL_TRANSFER):
            recipient = self._active_info(tx.recipient, "получателя")
        tx.set_fee(fee)

        balance_before = balance_after = None
        if sender is not None:
            if sender["type"] != "premium":
                if sender["balance"] < 0:
                    raise TransactionRuleError("Переводы со счёта в минусе запрещены (кроме премиум)")
            debit = convert(tx.amount + fee, tx.currency, sender["currency"])
            if sender["type"] != "premium" and sender["balance"] - debit < 0:
                raise TransactionRuleError(
                    f"Операция уведёт баланс в минус ({sender['balance']} - {debit}); "
                    f"овердрафт доступен только на премиум-счёте"
                )
            balance_before = sender["balance"]
            bank.withdraw(tx.sender_account_id, debit)
            balance_after = bank.get_account_info(tx.sender_account_id)["balance"]

        if recipient is not None:
            credit = convert(tx.amount, tx.currency, recipient["currency"])
            try:
                bank.deposit(tx.recipient, credit)
            except (NightOperationError,) + self.PERMANENT_ERRORS as original:
                self._rollback(tx, balance_before, balance_after, original)
                raise

    def _rollback(self, tx, balance_before, balance_after, original):
        """Если списали, а зачислить не вышло, возвращаем отправителю всё списанное"""
        if balance_before is None:
            return
        refund = round(balance_before - balance_after, 2)
        try:
            self._bank.deposit(tx.sender_account_id, refund)
        except (NightOperationError,) + self.PERMANENT_ERRORS as rollback_error:
            self._log(tx, rollback_error, "(откат не удался!)")
            raise TransactionRuleError(
                f"Зачисление не удалось ({original}), а возврат {refund} отправителю тоже: {rollback_error}"
            ) from rollback_error