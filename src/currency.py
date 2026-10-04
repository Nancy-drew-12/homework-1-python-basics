from src.bank_account import is_valid_amount
from src.exceptions import InvalidOperationError

# Учебные фиксированные курсы: сколько рублей стоит единица валюты
RATES_TO_RUB = {"RUB": 1.0, "USD": 90.0, "EUR": 100.0, "KZT": 0.2, "CNY": 12.5}


def convert(amount: float, from_currency: str, to_currency: str) -> float:
    """Конвертация по фиксированным курсам, результат округляется до копеек"""
    if not is_valid_amount(amount):
        raise InvalidOperationError("Сумма конвертации должна быть конечным положительным числом")
    for currency in (from_currency, to_currency):
        if currency not in RATES_TO_RUB:
            raise InvalidOperationError(f"Нет курса для валюты: {currency}")
    if from_currency == to_currency:
        return round(amount, 2)
    return round(amount * RATES_TO_RUB[from_currency] / RATES_TO_RUB[to_currency], 2)