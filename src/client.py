import hashlib
import hmac
import os
import re
from datetime import date

from src.bank_account import generate_short_uuid
from src.exceptions import InvalidOperationError, UnderageClientError

MIN_AGE = 18


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000).hex()


class Client:
    """Клиент банка: ФИО, ID, статус, контакты, список номеров счетов"""

    def __init__(self, full_name: str, birth_date: date, phone: str, email: str,
                 password: str, client_id: str = None, today: date = None):
        if not isinstance(full_name, str) or len(full_name.split()) < 2:
            raise InvalidOperationError("ФИО должно быть строкой минимум из двух слов")

        if not isinstance(birth_date, date):
            raise InvalidOperationError("Дата рождения должна быть объектом date")
        today = today or date.today()
        if birth_date > today:
            raise InvalidOperationError("Дата рождения не может быть в будущем")
        if self._calc_age(birth_date, today) < MIN_AGE:
            raise UnderageClientError(f"Клиенту должно быть не менее {MIN_AGE} лет")

        if not isinstance(phone, str) or not re.fullmatch(r"\+?\d{10,15}", re.sub(r"[ \-()]", "", phone)):
            raise InvalidOperationError("Некорректный номер телефона")
        if not isinstance(email, str) or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise InvalidOperationError("Некорректный email")

        if not isinstance(password, str) or len(password) < 6:
            raise InvalidOperationError("Пароль должен быть строкой минимум из 6 символов")

        if client_id is None:
            client_id = generate_short_uuid()
        elif not isinstance(client_id, str) or not client_id:
            raise InvalidOperationError("ID клиента должен быть непустой строкой")

        self._full_name = full_name.strip()
        self._birth_date = birth_date
        self._contacts = {"phone": phone, "email": email}
        self._client_id = client_id
        self._status = "active"  # active | blocked
        self._account_ids = []
        self._failed_attempts = 0
        self._salt = os.urandom(16)
        self._password_hash = _hash_password(password, self._salt)

    @staticmethod
    def _calc_age(birth_date: date, today: date) -> int:
        had_birthday = (today.month, today.day) >= (birth_date.month, birth_date.day)
        return today.year - birth_date.year - (0 if had_birthday else 1)

    @property
    def full_name(self) -> str:
        return self._full_name

    @property
    def client_id(self) -> str:
        return self._client_id

    @property
    def status(self) -> str:
        return self._status

    @property
    def contacts(self) -> dict:
        return dict(self._contacts)

    @property
    def account_ids(self) -> list:
        return list(self._account_ids)

    @property
    def failed_attempts(self) -> int:
        return self._failed_attempts

    def add_account(self, account_id: str):
        self._account_ids.append(account_id)

    def check_password(self, password) -> bool:
        if not isinstance(password, str):
            return False
        return hmac.compare_digest(_hash_password(password, self._salt), self._password_hash)

    def register_failed_attempt(self) -> int:
        self._failed_attempts += 1
        return self._failed_attempts

    def reset_failed_attempts(self):
        self._failed_attempts = 0

    def block(self):
        self._status = "blocked"

    def unblock(self):
        self._status = "active"
        self._failed_attempts = 0

    def __str__(self):
        return (
            f"Client({self._full_name}, ID={self._client_id}, статус={self._status}, "
            f"счетов={len(self._account_ids)})"
        )