from abc import ABC, abstractmethod


class AbstractAccount(ABC):
    """
    Абстрактная модель банковского счёта.
    Задаёт контракт, который обязаны реализовать все конкретные типы счетов.
    """

    def __init__(self, account_id: str, owner: str):
        self._account_id = account_id
        self._owner = owner
        self._balance = 0.0
        self._status = "active"  # active | frozen | closed

    @abstractmethod
    def deposit(self, amount: float):
        """Пополнение счёта"""
        pass

    @abstractmethod
    def withdraw(self, amount: float):
        """Снятие средств со счёта"""
        pass

    @abstractmethod
    def get_account_info(self) -> dict:
        """Возвращает информацию о счёте"""
        pass
