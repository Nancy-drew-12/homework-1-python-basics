"""День 6: демонстрация банковской системы целиком.

Запуск из корня проекта:  python demo.py
"""
import os
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.audit import AuditLog, Severity
from src.bank import Bank
from src.client import Client
from src.currency import convert
from src.exceptions import AuthenticationError, ClientBlockedError, InvalidOperationError
from src.risk import RiskAnalyzer
from src.transaction import Priority, Transaction, TransactionType as T
from src.transaction_processor import TransactionProcessor
from src.transaction_queue import TransactionQueue

TYPE_RU = {
    T.DEPOSIT: "пополнение",
    T.WITHDRAWAL: "снятие",
    T.INTERNAL_TRANSFER: "перевод",
    T.EXTERNAL_TRANSFER: "внешний перевод",
}

CLIENTS = [
    ("c-anna", "Анна Петрова", date(1990, 5, 17)),
    ("c-boris", "Борис Орлов", date(1985, 1, 2)),
    ("c-vera", "Вера Соколова", date(1992, 11, 23)),
    ("c-gleb", "Глеб Миронов", date(1988, 3, 9)),
    ("c-dina", "Дина Захарова", date(1995, 7, 30)),
    ("c-egor", "Егор Фролов", date(1979, 12, 4)),
    ("c-zoya", "Зоя Лебедева", date(2000, 2, 14)),
    ("c-ilya", "Илья Назаров", date(1983, 9, 21)),
]


class SimClock:
    """Часы симуляции: время двигаем вручную, поэтому результат всегда одинаковый"""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)

    def set(self, now):
        self.now = now


def to_rub(amount: float, currency: str) -> float:
    """Перевод в рубли. convert() принимает только положительные суммы,
    а у нас бывают нули (комиссия) и минус (овердрафт) - их обрабатываем отдельно"""
    if amount == 0:
        return 0.0
    sign = 1 if amount > 0 else -1
    return sign * convert(abs(amount), currency, "RUB")


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


class Demo:
    def __init__(self, output_dir: str, verbose: bool = True):
        self.verbose = verbose
        os.makedirs(output_dir, exist_ok=True)
        self.log_path = os.path.join(output_dir, "demo_audit.log")
        self.clock = SimClock(datetime(2026, 10, 5, 10, 0))
        self.bank = Bank("ItGrind Bank", clock=self.clock,
                         audit=AuditLog(self.log_path, clock=self.clock))
        self.queue = TransactionQueue()
        self.processor = TransactionProcessor(self.bank, self.queue)
        self.acc = {}       # короткое имя -> номер счёта
        self.label = {}     # номер счёта -> короткое имя
        self._n = 0
        self.rejected_on_create = 0

    # ---------- вывод ----------

    def say(self, text=""):
        if self.verbose:
            print(text)

    def title(self, text):
        self.say()
        self.say(f"=== {text} ===")

    def lab(self, account):
        return self.label.get(account, account)

    def stamp(self):
        return f"{self.clock.now:%d.%m %H:%M}"

    # ---------- инициализация ----------

    def fund(self, account_id, amount):
        """Стартовое пополнение счёта через банк.

        Банк проверяет риск у любого пополнения, а сумма от 200 000 RUB считается крупной.
        Поэтому большие суммы вносим частями ниже этого порога и между частями двигаем часы:
        так пополнения не выглядят «частыми операциями» (больше 8 за 10 минут).
        """
        currency = self.bank.get_account_info(account_id)["currency"]
        portion = convert(RiskAnalyzer.LARGE_AMOUNT - 1, "RUB", currency)
        left = amount
        while left > 0:
            part = min(left, portion)
            self.bank.deposit(account_id, part)
            left = round(left - part, 2)
            self.clock.advance(minutes=2)

    def open(self, key, client_id, account_type, currency, balance=0, **options):
        """Открывает счёт и (если нужно) кладёт на него стартовую сумму через банк"""
        account_id = self.bank.open_account(client_id, account_type, currency, **options)
        if balance:
            self.fund(account_id, balance)
        self.acc[key] = account_id
        self.label[account_id] = key
        return account_id

    def init_bank(self):
        self.title("1. Инициализация: банк, клиенты, счета")
        self.clock.set(datetime(2026, 10, 5, 9, 0))   # стартовые пополнения идут до 10:00, с шагом по времени
        for index, (client_id, name, born) in enumerate(CLIENTS, start=1):
            client = Client(name, born, f"+7900000{index:04d}", f"{client_id[2:]}@mail.ru",
                            "secret123", client_id=client_id)
            self.bank.add_client(client)
            self.say(f"  {client}")

        self.open("anna-main", "c-anna", "bank", "RUB", balance=150_000)
        self.open("anna-sav", "c-anna", "savings", "RUB", balance=300_000,
                  min_balance=10_000, monthly_rate=0.01)
        self.open("boris-prem", "c-boris", "premium", "USD", balance=2_000,
                  overdraft_limit=1_000, fixed_fee=5)
        self.open("boris-main", "c-boris", "bank", "RUB", balance=80_000)
        self.open("vera-rub", "c-vera", "bank", "RUB", balance=500_000)
        self.open("vera-eur", "c-vera", "bank", "EUR", balance=3_000)
        self.open("gleb-inv", "c-gleb", "investment", "RUB", balance=200_000)
        self.open("gleb-main", "c-gleb", "bank", "RUB", balance=40_000)
        self.open("dina-main", "c-dina", "bank", "RUB", balance=60_000)
        self.open("egor-main", "c-egor", "bank", "RUB", balance=1_500_000)
        self.open("egor-save", "c-egor", "bank", "RUB", balance=0)
        self.open("egor-frozen", "c-egor", "bank", "RUB", balance=10_000)
        self.open("zoya-sav", "c-zoya", "savings", "RUB", balance=90_000,
                  min_balance=5_000, monthly_rate=0.005)
        self.open("ilya-kzt", "c-ilya", "bank", "KZT", balance=400_000)

        self.bank.invest(self.acc["gleb-inv"], "stocks", 50_000)
        self.bank.freeze_account(self.acc["egor-frozen"])
        self.clock.set(datetime(2026, 10, 5, 10, 0))   # дальше симуляция идёт как раньше, с 10:00
        self.say(f"Клиентов: {len(CLIENTS)}, счетов: {len(self.acc)} "
                 f"(счёт egor-frozen заморожен, у gleb-inv часть денег в акциях)")

    # ---------- очередь ----------

    def enqueue(self, tx_type, amount, currency, sender=None, recipient=None,
                priority=Priority.NORMAL, delay=None):
        """Создаёт транзакцию, кладёт в очередь, пишет об этом в консоль и аудит.
        sender/recipient - короткие имена счетов из демо (или готовый номер/внешний получатель)"""
        self._n += 1
        tx_id = f"tx-{self._n:02d}"
        sender_id = self.acc.get(sender, sender)
        recipient_id = self.acc.get(recipient, recipient)
        now = self.clock.now
        tx = Transaction(tx_type, amount, currency, sender_account_id=sender_id,
                         recipient=recipient_id, priority=priority,
                         execute_at=now + delay if delay else None,
                         created_at=now, transaction_id=tx_id)
        self.queue.add(tx)
        client = self.bank.owner_of(sender_id) or self.bank.owner_of(recipient_id)
        self.bank.audit.log(Severity.INFO, "tx_queued",
                            f"{tx_id}: {TYPE_RU[tx_type]} {amount} {currency} поставлена в очередь",
                            client_id=client, tx_id=tx_id)
        self.say(f"  [ОЧЕРЕДЬ]    {tx_id} | {TYPE_RU[tx_type]:<15} | {money(amount):>13} {currency} | "
                 f"{self.lab(sender_id) if sender_id else '-':<11} -> "
                 f"{self.lab(recipient_id) if recipient_id else '-'}"
                 + (" | приоритет ВЫСОКИЙ" if priority == Priority.HIGH else "")
                 + (f" | отложена до {tx.execute_at:%H:%M}" if delay else ""))
        return tx

    def reject_on_create(self, label, factory):
        """Некорректную транзакцию отклоняет сам объект Transaction: в очередь она не попадает"""
        try:
            factory()
        except InvalidOperationError as e:
            self.rejected_on_create += 1
            self.bank.audit.log(Severity.WARNING, "tx_rejected", f"{label}: {e}")
            self.say(f"  [ОТКЛОНЕНО]  при создании ({label}): {e}")

    def process(self):
        """Исполняет всё, что готово, и показывает итог по каждой транзакции"""
        before = len(self.bank.audit)
        processed = self.processor.process_due()
        warnings = [e for e in self.bank.audit.entries[before:] if e["event"] == "risk_warning"]
        for tx in processed:
            if tx.status == "completed":
                fee = f", комиссия {money(tx.fee)}" if tx.fee else ""
                self.say(f"  [ВЫПОЛНЕНО]  {tx.id}{fee}")
            elif tx.status == "failed":
                self.say(f"  [ОТКЛОНЕНО]  {tx.id}: {tx.failure_reason}")
            else:
                self.say(f"  [ОТЛОЖЕНО]   {tx.id}: ночное время, следующая попытка {tx.execute_at:%d.%m %H:%M}")
        for entry in warnings:
            self.say(f"  [ПРЕДУПРЕЖДЕНИЕ] {entry['message']}")

    # ---------- симуляция ----------

    def simulate(self):
        c, a = self.clock, self.acc

        self.title("2. Симуляция: обычные операции (10:00)")
        self.enqueue(T.DEPOSIT, 20_000, "RUB", recipient="anna-main")
        self.enqueue(T.INTERNAL_TRANSFER, 5_000, "RUB", "anna-main", "boris-main")
        self.enqueue(T.INTERNAL_TRANSFER, 15_000, "RUB", "vera-rub", "dina-main")
        self.enqueue(T.WITHDRAWAL, 3_000, "RUB", "dina-main")
        self.enqueue(T.INTERNAL_TRANSFER, 50, "USD", "boris-prem", "vera-eur")
        self.enqueue(T.EXTERNAL_TRANSFER, 12_000, "RUB", "boris-main", "EXT-ЖКХ-555",
                     priority=Priority.HIGH)
        self.enqueue(T.DEPOSIT, 100, "EUR", recipient="vera-eur")
        self.enqueue(T.INTERNAL_TRANSFER, 8_000, "RUB", "gleb-main", "anna-main")
        self.enqueue(T.WITHDRAWAL, 2_000, "RUB", "zoya-sav")
        self.enqueue(T.INTERNAL_TRANSFER, 100_000, "KZT", "ilya-kzt", "dina-main")
        self.enqueue(T.DEPOSIT, 30_000, "RUB", recipient="egor-main")
        self.process()

        c.advance(minutes=15)
        self.title(f"3. Ошибочные операции ({c.now:%H:%M})")
        self.enqueue(T.WITHDRAWAL, 500_000, "RUB", "dina-main")                       # нет денег
        self.enqueue(T.INTERNAL_TRANSFER, 1_000, "RUB", "anna-main", "egor-frozen")   # счёт заморожен
        self.enqueue(T.INTERNAL_TRANSFER, 700, "RUB", "anna-main", "no-such-acc")     # счёта нет
        self.enqueue(T.WITHDRAWAL, 85_000, "RUB", "zoya-sav")                         # ниже мин. остатка
        self.enqueue(T.WITHDRAWAL, 5_000, "USD", "boris-prem")                        # овердрафт
        self.process()

        c.advance(minutes=15)
        self.title(f"4. Некорректные данные отклоняются при создании ({c.now:%H:%M})")
        now = c.now
        self.reject_on_create("сумма -100", lambda: Transaction(
            T.DEPOSIT, -100, "RUB", recipient=a["anna-main"], created_at=now))
        self.reject_on_create("валюта ABC", lambda: Transaction(
            T.DEPOSIT, 100, "ABC", recipient=a["anna-main"], created_at=now))
        self.reject_on_create("перевод на тот же счёт", lambda: Transaction(
            T.INTERNAL_TRANSFER, 100, "RUB", sender_account_id=a["anna-main"],
            recipient=a["anna-main"], created_at=now))

        self.title(f"5. Подозрительные операции Егора ({c.now:%H:%M})")
        self.enqueue(T.INTERNAL_TRANSFER, 300_000, "RUB", "egor-main", "vera-rub")   # крупная + новый
        self.enqueue(T.EXTERNAL_TRANSFER, 250_000, "RUB", "egor-main", "ООО Тайга")  # крупная + новый
        self.enqueue(T.INTERNAL_TRANSFER, 1_200_000, "RUB", "egor-main", "anna-main")  # очень крупная
        self.enqueue(T.INTERNAL_TRANSFER, 250_000, "RUB", "egor-main", "egor-save")  # крупная, но свой счёт
        self.process()

        c.advance(minutes=15)
        self.title(f"6. Серия частых операций Дины: 10 переводов за минуту ({c.now:%H:%M})")
        for _ in range(10):
            self.enqueue(T.INTERNAL_TRANSFER, 100, "RUB", "dina-main", "vera-rub")
        self.process()

        c.advance(minutes=15)
        self.title(f"7. Отложенные операции и отмена ({c.now:%H:%M})")
        delayed = self.enqueue(T.INTERNAL_TRANSFER, 4_000, "RUB", "anna-main", "gleb-main",
                               delay=timedelta(hours=2))
        cancelled = self.enqueue(T.INTERNAL_TRANSFER, 9_000, "RUB", "anna-main", "gleb-main",
                                 delay=timedelta(hours=2))
        self.queue.cancel(cancelled.id, c.now)
        self.bank.audit.log(Severity.INFO, "tx_cancelled", f"{cancelled.id}: отменена пользователем",
                            client_id="c-anna", tx_id=cancelled.id)
        self.say(f"  [ОТМЕНЕНО]   {cancelled.id}: отменена пользователем до исполнения")
        self.process()

        self.title(f"8. Подбор пароля: Илья вводит неверный пароль ({c.now:%H:%M})")
        for attempt in range(1, 4):
            try:
                self.bank.authenticate_client("c-ilya", "wrong-pass")
            except (AuthenticationError, ClientBlockedError) as e:
                self.say(f"  попытка {attempt}: {type(e).__name__}: {e}")
        try:
            self.bank.authenticate_client("c-ilya", "secret123")
        except ClientBlockedError as e:
            self.say(f"  даже верный пароль не пускает: {e}")
        self.bank.unblock_client("c-ilya")
        self.say("  оператор банка разблокировал клиента: "
                 f"вход {'успешен' if self.bank.authenticate_client('c-ilya', 'secret123') else 'не удался'}")

        c.set(datetime(2026, 10, 5, 13, 0))
        self.title(f"9. Наступило время отложенной операции ({c.now:%H:%M})")
        self.process()

        c.set(datetime(2026, 10, 6, 3, 30))
        self.title(f"10. Ночь ({c.now:%d.%m %H:%M}): операции откладываются до 05:00")
        self.enqueue(T.DEPOSIT, 1_000, "RUB", recipient="boris-main")
        self.enqueue(T.WITHDRAWAL, 2_500, "RUB", "boris-main")
        self.process()
        c.set(datetime(2026, 10, 6, 5, 0))
        self.say(f"  --- {c.now:%d.%m %H:%M}, банк снова работает ---")
        self.process()

        c.set(datetime(2026, 10, 6, 9, 0))
        self.title(f"11. Обычные операции утром ({c.now:%d.%m %H:%M})")
        self.enqueue(T.INTERNAL_TRANSFER, 2_000, "RUB", "anna-main", "boris-main")
        self.enqueue(T.DEPOSIT, 10_000, "RUB", recipient="zoya-sav")
        self.enqueue(T.EXTERNAL_TRANSFER, 3_000, "RUB", "gleb-main", "EXT-МТС-100")
        self.enqueue(T.INTERNAL_TRANSFER, 20, "EUR", "vera-eur", "boris-prem")
        self.process()

    # ---------- пользовательские сценарии ----------

    def client_accounts(self, client_id):
        self.title(f"12. Сценарий: счета клиента {client_id}")
        for info in self.bank.search_accounts(client_id=client_id):
            self.say(f"  {self.bank.describe_account(info['account_id'])}")

    def client_history(self, client_id):
        self.title(f"13. Сценарий: история операций клиента {client_id}")
        own = {info["account_id"] for info in self.bank.search_accounts(client_id=client_id)}
        rows = [tx for tx in self.queue.all_transactions()
                if tx.sender_account_id in own or tx.recipient in own]
        rows.sort(key=lambda tx: tx.created_at)
        for tx in rows:
            direction = "исходящая" if tx.sender_account_id in own else "входящая"
            reason = f" | {tx.failure_reason}" if tx.failure_reason else ""
            self.say(f"  {tx.created_at:%d.%m %H:%M} | {tx.id} | {direction:<9} | "
                     f"{TYPE_RU[tx.type]:<15} | {money(tx.amount):>12} {tx.currency} | {tx.status}{reason}")
        self.say(f"  Всего операций: {len(rows)}")

    def client_suspicious(self, client_id):
        self.title(f"14. Сценарий: подозрительные операции клиента {client_id}")
        reports = self.bank.audit_reports()
        rows = [r for r in reports.suspicious_operations() if r["client_id"] == client_id]
        for r in rows:
            self.say(f"  {r['time']:%d.%m %H:%M} | риск {r['level']:<6} ({r['score']:>2}) | {r['reasons']}")
        profile = reports.client_risk_profile(client_id)
        self.say(f"  Риск-профиль: общий уровень {profile['overall_level']}, "
                 f"операций {profile['operations']}, по уровням {profile['by_level']}")
        blocked = [e for e in self.bank.audit.filter(client_id=client_id, event="risk_blocked")]
        self.say(f"  Заблокировано банком: {len(blocked)}")

    # ---------- отчёты ----------

    def client_total_rub(self, client_id):
        return sum(to_rub(i["total_value"], i["currency"])
                   for i in self.bank.search_accounts(client_id=client_id))

    def reports(self):
        self.title("15. Отчёт: топ-3 клиента по сумме на счетах (в рублях)")
        ranking = sorted(((self.client_total_rub(cid), name) for cid, name, _ in CLIENTS), reverse=True)
        for place, (total, name) in enumerate(ranking[:3], start=1):
            self.say(f"  {place}. {name}: {money(total)} RUB")

        self.title("16. Отчёт: статистика транзакций")
        stats = self.transaction_stats()
        self.say(f"  Всего в очереди: {stats['total']}  (ещё {stats['rejected_on_create']} отклонены при создании)")
        self.say(f"  По статусам: {stats['by_status']}")
        self.say(f"  По типам:    {stats['by_type']}")
        self.say(f"  Объём выполненных: {money(stats['completed_volume_rub'])} RUB, "
                 f"комиссии: {money(stats['fees_rub'])} RUB")
        errors = self.bank.audit_reports().error_statistics()
        self.say(f"  Ошибки в аудите: {errors['total_errors']} {errors['by_error_type']}")

        self.title("17. Отчёт: общий баланс банка")
        totals = self.bank.get_total_balance()
        for currency, value in totals.items():
            self.say(f"  {currency}: {money(value)}")
        self.say(f"  Всего в рублях: {money(self.total_rub())} RUB")

        self.say()
        self.say(f"Журнал аудита ({len(self.bank.audit)} записей) сохранён в файл: {self.log_path}")

    def transaction_stats(self):
        txs = self.queue.all_transactions()
        by_status, by_type = {}, {}
        volume = fees = 0.0
        for tx in txs:
            by_status[tx.status] = by_status.get(tx.status, 0) + 1
            by_type[tx.type] = by_type.get(tx.type, 0) + 1
            if tx.status == "completed":
                volume += to_rub(tx.amount, tx.currency)
                fees += to_rub(tx.fee, tx.currency)
        return {"total": len(txs), "by_status": by_status, "by_type": by_type,
                "completed_volume_rub": round(volume, 2), "fees_rub": round(fees, 2),
                "rejected_on_create": self.rejected_on_create}

    def total_rub(self):
        return round(sum(to_rub(v, cur) for cur, v in self.bank.get_total_balance().items()), 2)


def run_demo(output_dir: str = None, verbose: bool = True) -> Demo:
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    demo = Demo(output_dir, verbose)
    demo.init_bank()
    demo.simulate()
    demo.client_accounts("c-anna")
    demo.client_history("c-anna")
    demo.client_suspicious("c-egor")
    demo.reports()
    return demo


if __name__ == "__main__":
    run_demo()