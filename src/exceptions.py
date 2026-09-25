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



