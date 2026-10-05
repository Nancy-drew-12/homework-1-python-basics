from src.bank import Bank
from src.bank_account import is_valid_non_negative
from src.audit import Severity
from src.currency import convert
from src.exceptions import (
    AccountClosedError,
    AccountFrozenError,
    AccountNotFoundError,
    InsufficientFundsError,
    InvalidOperationError,
    NightOperationError,
    RiskBlockedError,
    TransactionRuleError,
)
from src.transaction import Transaction, TransactionType
from src.transaction_queue import TransactionQueue


class TransactionProcessor:
    """Выполняет транзакции из очереди: комиссии, конвертация, повторы, журнал ошибок.

    Деньги двигаются только через Bank.settle: там ночной запрет, риск-анализ,
    аудит и откат при ошибке.
    """

    EXTERNAL_FEE_RATE = 0.01  # 1% за внешний перевод
    PERMANENT_ERRORS = (
        AccountFrozenError, AccountClosedError, InsufficientFundsError,
        InvalidOperationError, AccountNotFoundError, TransactionRuleError,
        RiskBlockedError,
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

    @staticmethod
    def _kind(tx: Transaction) -> str:
        """Тип транзакции строкой: 'deposit', 'internal_transfer', ..."""
        return getattr(tx.type, "name", str(tx.type)).lower()

    def _client_of(self, tx: Transaction):
        """Клиент, от имени которого идёт операция (для аудита и риска)"""
        return self._bank.owner_of(tx.sender_account_id) or self._bank.owner_of(tx.recipient)

    def _process(self, tx: Transaction):
        now = self._bank.now()
        audit = self._bank.audit
        client = self._client_of(tx)
        tx.register_attempt()
        try:
            if self._bank.is_night_now():
                # фиксируем попытку как ночной риск, затем откладываем транзакцию
                self._bank.risk_analyzer.record_night_attempt(client, now, self._kind(tx))
                raise NightOperationError("Ночное время: операции временно недоступны")
            self._apply(tx)
        except NightOperationError as e:
            self._log(tx, e)
            if tx.attempts >= self._max_attempts:
                message = f"Превышено число попыток ({tx.attempts}): {e}"
                tx.mark_failed(message, now)
                audit.log(Severity.ERROR, "tx_failed", f"{tx.id}: {message}",
                          client_id=client, tx_id=tx.id, error_type=type(e).__name__)
            else:
                tx.reschedule(self._bank.next_operating_time())
                self._queue.requeue(tx)
                audit.log(Severity.WARNING, "tx_rescheduled",
                          f"{tx.id}: ночь, повтор позже", client_id=client, tx_id=tx.id)
        except RiskBlockedError as e:
            # CRITICAL-запись "risk_blocked" уже сделал банк; здесь только итог по транзакции
            self._log(tx, e)
            tx.mark_failed(str(e), now)
            audit.log(Severity.WARNING, "tx_rejected", f"{tx.id}: {e}",
                      client_id=client, tx_id=tx.id)
        except self.PERMANENT_ERRORS as e:
            self._log(tx, e)
            tx.mark_failed(str(e), now)
            audit.log(Severity.ERROR, "tx_failed", f"{tx.id}: {e}",
                      client_id=client, tx_id=tx.id, error_type=type(e).__name__)
        except Exception as e:
            self._log(tx, e, "(непредвиденная ошибка)")
            tx.mark_failed(f"Непредвиденная ошибка: {e}", now)
            audit.log(Severity.CRITICAL, "tx_failed", f"{tx.id}: непредвиденная ошибка: {e}",
                      client_id=client, tx_id=tx.id, error_type=type(e).__name__)
            raise
        else:
            tx.mark_completed(now)
            audit.log(Severity.INFO, "tx_completed", f"{tx.id}: выполнена",
                      client_id=client, tx_id=tx.id)

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
        fee = self._calc_fee(tx)

        sender = None
        recipient = None
        if tx.sender_account_id is not None:
            sender = self._active_info(tx.sender_account_id, "отправителя")
        if tx.type in (TransactionType.DEPOSIT, TransactionType.INTERNAL_TRANSFER):
            recipient = self._active_info(tx.recipient, "получателя")
        tx.set_fee(fee)

        debit = credit = None
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
        if recipient is not None:
            credit = convert(tx.amount, tx.currency, recipient["currency"])

        # Деньги двигает банк: ночь -> риск (high блокируется) -> списание/зачисление
        # с автоматическим откатом -> аудит.
        self._bank.settle(
            self._kind(tx), tx.amount, tx.currency,
            sender_id=tx.sender_account_id, debit=debit,
            recipient_id=tx.recipient if recipient is not None else None, credit=credit,
            external_recipient=tx.recipient if tx.type == TransactionType.EXTERNAL_TRANSFER else None,
            fee=fee,
        )