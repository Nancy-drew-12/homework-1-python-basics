from datetime import datetime

from src.exceptions import InvalidOperationError
from src.transaction import Transaction, TransactionStatus


class TransactionQueue:
    """Очередь: приоритеты, отложенные операции, отмена.

    Порядок среди готовых к выполнению: приоритет, затем время, затем порядок добавления.
    """

    def __init__(self):
        self._all = {}       # id -> Transaction (в том числе уже обработанные)
        self._pending = {}   # id -> Transaction (ждут выполнения)
        self._order = {}     # id -> порядковый номер добавления
        self._seq = 0

    def _push(self, tx: Transaction):
        self._seq += 1
        self._order[tx.id] = self._seq
        self._pending[tx.id] = tx

    def add(self, tx: Transaction):
        if not isinstance(tx, Transaction):
            raise InvalidOperationError("В очередь можно добавить только Transaction")
        if tx.status != TransactionStatus.PENDING:
            raise InvalidOperationError("В очередь можно добавить только транзакцию в статусе pending")
        if tx.id in self._all:
            raise InvalidOperationError(f"Транзакция {tx.id} уже в очереди")
        self._all[tx.id] = tx
        self._push(tx)

    def requeue(self, tx: Transaction):
        """Вернуть в очередь транзакцию, которую отложили (повторная попытка)"""
        if self._all.get(tx.id) is not tx or tx.status != TransactionStatus.PENDING:
            raise InvalidOperationError("Вернуть в очередь можно только свою pending-транзакцию")
        self._push(tx)

    def cancel(self, tx_id: str, when: datetime):
        tx = self._all.get(tx_id)
        if tx is None:
            raise InvalidOperationError(f"Транзакция {tx_id} не найдена")
        if tx_id not in self._pending:
            raise InvalidOperationError(f"Транзакцию {tx_id} уже нельзя отменить (статус {tx.status})")
        tx.cancel(when)
        del self._pending[tx_id]

    def pop_due(self, now: datetime):
        """Достаёт самую важную из готовых к выполнению транзакций или None"""
        due = [tx for tx in self._pending.values() if tx.execute_at <= now]
        if not due:
            return None
        best = min(due, key=lambda tx: (tx.priority, tx.execute_at, self._order[tx.id]))
        del self._pending[best.id]
        return best

    def get(self, tx_id: str) -> Transaction:
        tx = self._all.get(tx_id)
        if tx is None:
            raise InvalidOperationError(f"Транзакция {tx_id} не найдена")
        return tx

    def pending_count(self) -> int:
        return len(self._pending)

    def all_transactions(self) -> list:
        return list(self._all.values())