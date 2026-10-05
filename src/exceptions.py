class AccountFrozenError(Exception):
    """Операция невозможна: счёт заморожен"""
    pass


class AccountClosedError(Exception):
    """Операция невозможна: счёт закрыт"""
    pass


class InvalidOperationError(Exception):
    """Некорректные входные данные операции"""
    pass


class InsufficientFundsError(Exception):
    """Недостаточно средств на счёте"""
    pass

class ClientNotFoundError(Exception):
    """Клиент не найден"""
    pass


class AccountNotFoundError(Exception):
    """Счёт не найден"""
    pass


class AuthenticationError(Exception):
    """Неверные данные для входа"""
    pass


class ClientBlockedError(Exception):
    """Клиент заблокирован"""
    pass


class NightOperationError(Exception):
    """Операции запрещены с 00:00 до 05:00"""
    pass


class UnderageClientError(Exception):
    """Клиенту меньше 18 лет"""
    pass

class TransactionRuleError(Exception):
    """Нарушено правило обработки транзакции"""
    pass

class RiskBlockedError(Exception):
    """Операция заблокирована системой рисков"""


