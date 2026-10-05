import csv
import json
import os
from datetime import datetime
from enum import Enum

import matplotlib

matplotlib.use("Agg")  # рисуем в файлы, без окон (работает и без экрана)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

from src.bank import Bank  # noqa: E402
from src.currency import convert  # noqa: E402
from src.exceptions import InvalidOperationError  # noqa: E402
from src.transaction_queue import TransactionQueue  # noqa: E402

# какая таблица экспортируется в CSV по умолчанию для каждого типа отчёта
DEFAULT_CSV_SECTION = {"client": "accounts", "bank": "accounts", "risk": "suspicious_operations"}
TYPE_RU = {"bank": "обычный", "savings": "сберегательный", "premium": "премиум",
           "investment": "инвестиционный"}


def to_rub(amount: float, currency: str) -> float:
    """Перевод в рубли. convert() принимает только положительные суммы,
    а в отчётах бывают нули и минус (овердрафт) - их обрабатываем отдельно"""
    if amount == 0:
        return 0.0
    sign = 1 if amount > 0 else -1
    return sign * convert(abs(amount), currency, "RUB")


def money(value: float) -> str:
    return f"{value:,.2f}".replace(",", " ")


def _rub_axis(ax):
    """Подписи оси Y обычными числами: 1 500 000 вместо 1e6"""
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", " ")))


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, Enum):
        return value.value
    return str(value)


class ReportBuilder:
    """Собирает отчёты по клиенту, банку и рискам; выгружает в текст, JSON, CSV и рисует графики.

    Отчёт - обычный словарь: его можно напечатать (to_text), сохранить (export_to_json,
    export_to_csv) или использовать дальше. Данные берутся только через публичные методы банка.
    """

    def __init__(self, bank: Bank, queue: TransactionQueue = None):
        if not isinstance(bank, Bank):
            raise InvalidOperationError("ReportBuilder нужен объект Bank")
        if queue is not None and not isinstance(queue, TransactionQueue):
            raise InvalidOperationError("queue должен быть объектом TransactionQueue")
        self._bank = bank
        self._queue = queue

    # ---------- сбор данных ----------

    def _accounts_of(self, client_id: str) -> list:
        rows = []
        for info in self._bank.search_accounts(client_id=client_id):
            rows.append({
                "account_id": info["account_id"],
                "type": info["type"],
                "currency": info["currency"],
                "status": info["status"],
                "balance": info["balance"],
                "total_value": info["total_value"],
                "total_value_rub": round(to_rub(info["total_value"], info["currency"]), 2),
            })
        return rows

    def _transactions_of(self, account_ids: set) -> list:
        if self._queue is None:
            return []
        rows = []
        for tx in self._queue.all_transactions():
            outgoing = tx.sender_account_id in account_ids
            if not (outgoing or tx.recipient in account_ids):
                continue
            rows.append({
                "id": tx.id,
                "created_at": tx.created_at,
                "direction": "исходящая" if outgoing else "входящая",
                "type": tx.type,
                "amount": tx.amount,
                "currency": tx.currency,
                "fee": tx.fee,
                "status": tx.status,
                "failure_reason": tx.failure_reason or "",
            })
        rows.sort(key=lambda r: r["created_at"])
        return rows

    def _transaction_stats(self) -> dict:
        txs = self._queue.all_transactions() if self._queue is not None else []
        by_status, by_type = {}, {}
        volume = fees = 0.0
        for tx in txs:
            by_status[tx.status] = by_status.get(tx.status, 0) + 1
            by_type[tx.type] = by_type.get(tx.type, 0) + 1
            if tx.status == "completed":
                volume += to_rub(tx.amount, tx.currency)
                fees += to_rub(tx.fee, tx.currency)
        return {"total": len(txs), "by_status": by_status, "by_type": by_type,
                "completed_volume_rub": round(volume, 2), "fees_rub": round(fees, 2)}

    # ---------- три типа отчётов ----------

    def client_report(self, client_id: str) -> dict:
        """Отчёт по клиенту: данные, счета, операции, движение денег, риск-профиль"""
        info = self._bank.get_client_info(client_id)   # ClientNotFoundError, если нет такого
        accounts = self._accounts_of(client_id)
        ids = {a["account_id"] for a in accounts}
        return {
            "type": "client",
            "generated_at": self._bank.now(),
            "client": info,
            "accounts": accounts,
            "total_rub": round(sum(a["total_value_rub"] for a in accounts), 2),
            "transactions": self._transactions_of(ids),
            "ledger": self._bank.get_ledger(client_id=client_id),
            "risk": self._bank.audit_reports().client_risk_profile(client_id),
        }

    def bank_report(self) -> dict:
        """Отчёт по банку: клиенты, счета по типам, суммы, топ клиентов, статистика транзакций"""
        clients = self._bank.list_clients()
        accounts, by_type, client_rows = [], {}, []
        for client in clients:
            rows = self._accounts_of(client["client_id"])
            total = round(sum(a["total_value_rub"] for a in rows), 2)
            client_rows.append({"client_id": client["client_id"], "full_name": client["full_name"],
                                "status": client["status"], "accounts": len(rows), "total_rub": total})
            for a in rows:
                accounts.append(dict(a, client_id=client["client_id"], owner=client["full_name"]))
                bucket = by_type.setdefault(a["type"], {"count": 0, "total_rub": 0.0})
                bucket["count"] += 1
                bucket["total_rub"] = round(bucket["total_rub"] + a["total_value_rub"], 2)
        client_rows.sort(key=lambda r: (-r["total_rub"], r["full_name"]))
        return {
            "type": "bank",
            "generated_at": self._bank.now(),
            "bank": self._bank.name,
            "clients_count": len(clients),
            "accounts_count": len(accounts),
            "totals_by_currency": self._bank.get_total_balance(),
            "total_rub": round(sum(a["total_value_rub"] for a in accounts), 2),
            "accounts_by_type": by_type,
            "top_clients": client_rows[:3],
            "clients": client_rows,
            "transactions": self._transaction_stats(),
            "accounts": accounts,
        }

    def risk_report(self) -> dict:
        """Отчёт по рискам: подозрительные операции, профили клиентов, ошибки, блокировки"""
        reports = self._bank.audit_reports()
        analyzer = self._bank.risk_analyzer
        by_level = {}
        for record in analyzer.records():
            by_level[record.level.value] = by_level.get(record.level.value, 0) + 1
        profiles = [reports.client_risk_profile(c["client_id"]) for c in self._bank.list_clients()]
        profiles = [p for p in profiles if p["operations"] > 0]
        profiles.sort(key=lambda p: (-p["max_score"], p["client_id"]))
        blocked = self._bank.audit.filter(event="risk_blocked")
        return {
            "type": "risk",
            "generated_at": self._bank.now(),
            "operations_assessed": len(analyzer.records()),
            "by_level": {lvl: by_level.get(lvl, 0) for lvl in ("low", "medium", "high")},
            "blocked_count": len(blocked),
            "suspicious_actions_count": len(self._bank.get_suspicious_actions()),
            "suspicious_operations": reports.suspicious_operations(),
            "client_profiles": [{k: p[k] for k in ("client_id", "operations", "max_score",
                                                   "avg_score", "overall_level")}
                                for p in profiles],
            "errors": reports.error_statistics(),
        }

    # ---------- текст ----------

    def to_text(self, report: dict) -> str:
        kind = self._kind(report)
        builder = {"client": self._text_client, "bank": self._text_bank, "risk": self._text_risk}[kind]
        return "\n".join(builder(report)) + "\n"

    @staticmethod
    def _head(title, report):
        return [title, f"Сформирован: {report['generated_at']:%d.%m.%Y %H:%M}", "=" * 60]

    def _text_client(self, r):
        c = r["client"]
        lines = self._head(f"ОТЧЁТ ПО КЛИЕНТУ: {c['full_name']} ({c['client_id']})", r)
        lines.append(f"Статус: {c['status']}")
        lines.append(f"Всего на счетах: {money(r['total_rub'])} RUB")
        lines.append("")
        lines.append("Счета:")
        for a in r["accounts"]:
            lines.append(f"  {a['account_id']} | {TYPE_RU.get(a['type'], a['type']):<14} | {a['status']:<7} | "
                         f"{money(a['total_value']):>14} {a['currency']}")
        lines.append("")
        lines.append(f"Операции ({len(r['transactions'])}):")
        for t in r["transactions"]:
            reason = f" | {t['failure_reason']}" if t["failure_reason"] else ""
            lines.append(f"  {t['created_at']:%d.%m %H:%M} | {t['id']} | {t['direction']:<9} | {t['type']:<17} | "
                         f"{money(t['amount']):>13} {t['currency']} | {t['status']}{reason}")
        lines.append("")
        risk = r["risk"]
        lines.append(f"Риск-профиль: уровень {risk['overall_level']}, оценено операций {risk['operations']}, "
                     f"по уровням {risk['by_level']}")
        return lines

    def _text_bank(self, r):
        lines = self._head(f"ОТЧЁТ ПО БАНКУ: {r['bank']}", r)
        lines.append(f"Клиентов: {r['clients_count']}, счетов: {r['accounts_count']}")
        lines.append(f"Всего в рублях: {money(r['total_rub'])} RUB")
        lines.append("По валютам: " + ", ".join(f"{cur} {money(v)}" for cur, v in r["totals_by_currency"].items()))
        lines.append("")
        lines.append("Счета по типам:")
        for kind, data in r["accounts_by_type"].items():
            lines.append(f"  {TYPE_RU.get(kind, kind):<15} | счетов {data['count']:>2} | {money(data['total_rub']):>16} RUB")
        lines.append("")
        lines.append("Топ-3 клиента:")
        for place, c in enumerate(r["top_clients"], start=1):
            lines.append(f"  {place}. {c['full_name']}: {money(c['total_rub'])} RUB")
        t = r["transactions"]
        lines.append("")
        lines.append(f"Транзакции: всего {t['total']}, по статусам {t['by_status']}")
        lines.append(f"  Объём выполненных: {money(t['completed_volume_rub'])} RUB, комиссии: {money(t['fees_rub'])} RUB")
        return lines

    def _text_risk(self, r):
        lines = self._head("ОТЧЁТ ПО РИСКАМ", r)
        lines.append(f"Оценено операций: {r['operations_assessed']}, по уровням: {r['by_level']}")
        lines.append(f"Заблокировано банком: {r['blocked_count']}, подозрительных действий в журнале: "
                     f"{r['suspicious_actions_count']}")
        lines.append("")
        lines.append("Подозрительные операции:")
        for s in r["suspicious_operations"]:
            lines.append(f"  {s['time']:%d.%m %H:%M} | {s['client_id']:<8} | {s['level']:<6} ({s['score']:>2}) | "
                         f"{s['reasons']}")
        lines.append("")
        lines.append("Клиенты по уровню риска:")
        for p in r["client_profiles"]:
            lines.append(f"  {p['client_id']:<8} | {p['overall_level']:<6} | макс. балл {p['max_score']:>3} | "
                         f"операций {p['operations']}")
        e = r["errors"]
        lines.append("")
        lines.append(f"Ошибки: {e['total_errors']} из {e['total_entries']} записей аудита, {e['by_error_type']}")
        return lines

    # ---------- экспорт ----------

    @staticmethod
    def _kind(report) -> str:
        if not isinstance(report, dict) or report.get("type") not in DEFAULT_CSV_SECTION:
            raise InvalidOperationError("Нужен отчёт, собранный client_report/bank_report/risk_report")
        return report["type"]

    @staticmethod
    def _check_path(path):
        if not isinstance(path, str) or not path.strip():
            raise InvalidOperationError("Путь к файлу должен быть непустой строкой")
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

    def to_json(self, report: dict) -> str:
        self._kind(report)
        return json.dumps(report, ensure_ascii=False, indent=2, default=_json_default)

    def export_to_json(self, report: dict, path: str) -> str:
        """Сохраняет отчёт целиком в JSON-файл, возвращает путь"""
        self._check_path(path)
        text = self.to_json(report)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def export_to_csv(self, report: dict, path: str, section: str = None) -> str:
        """Сохраняет одну таблицу отчёта в CSV (по умолчанию: клиент и банк - счета, риски - подозрительные
        операции). section - имя любой таблицы отчёта: 'transactions', 'ledger', 'clients' и т.д."""
        kind = self._kind(report)
        section = section or DEFAULT_CSV_SECTION[kind]
        rows = report.get(section)
        if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
            raise InvalidOperationError(f"В отчёте '{kind}' нет таблицы '{section}'")
        self._check_path(path)
        fields = list(rows[0].keys()) if rows else []
        with open(path, "w", encoding="utf-8-sig", newline="") as f:   # utf-8-sig: Excel видит кириллицу
            writer = csv.writer(f, delimiter=";")
            writer.writerow(fields)
            for row in rows:
                writer.writerow([self._cell(row.get(name)) for name in fields])
        return path

    @staticmethod
    def _cell(value):
        if isinstance(value, datetime):
            return value.isoformat(sep=" ", timespec="seconds")
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=_json_default)
        return value

    # ---------- графики ----------

    def save_charts(self, directory: str, client_id: str = None) -> dict:
        """Рисует графики и сохраняет PNG в папку. Возвращает {название: путь к файлу}.

        pie - доли счетов (по банку - по типам счетов, по клиенту - по его счетам);
        bar - клиенты по сумме на счетах; line - движение баланса во времени;
        risk - число операций по уровням риска.
        """
        if not isinstance(directory, str) or not directory.strip():
            raise InvalidOperationError("Папка для графиков должна быть непустой строкой")
        if client_id is not None:
            self._bank.get_client_info(client_id)
        os.makedirs(directory, exist_ok=True)
        suffix = f"_{client_id}" if client_id else ""
        paths = {
            "pie": os.path.join(directory, f"pie{suffix}.png"),
            "bar": os.path.join(directory, "bar_clients.png"),
            "line": os.path.join(directory, f"balance_movement{suffix}.png"),
            "risk": os.path.join(directory, "risk_levels.png"),
        }
        self._chart_pie(paths["pie"], client_id)
        self._chart_bar(paths["bar"])
        self._chart_line(paths["line"], client_id)
        self._chart_risk(paths["risk"])
        return paths

    @staticmethod
    def _finish(fig, path):
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    @staticmethod
    def _no_data(ax):
        ax.text(0.5, 0.5, "нет данных", ha="center", va="center", fontsize=14, color="gray")
        ax.set_axis_off()

    def _chart_pie(self, path, client_id):
        fig, ax = plt.subplots(figsize=(7, 6))
        if client_id:
            rows = [(f"{a['type']} {a['account_id'][-4:]}", a["total_value_rub"])
                    for a in self._accounts_of(client_id)]
            title = f"Доли счетов клиента {client_id} (в рублях)"
        else:
            report = self.bank_report()
            rows = [(TYPE_RU.get(k, k), v["total_rub"]) for k, v in report["accounts_by_type"].items()]
            title = "Деньги банка по типам счетов (в рублях)"
        rows = [(label, value) for label, value in rows if value > 0]   # минус на круге не нарисовать
        if rows:
            ax.pie([v for _, v in rows], labels=[l for l, _ in rows], autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
        else:
            self._no_data(ax)
        ax.set_title(title)
        self._finish(fig, path)

    def _chart_bar(self, path):
        fig, ax = plt.subplots(figsize=(9, 5))
        clients = self.bank_report()["clients"]
        if clients:
            ax.bar([c["full_name"].split()[0] for c in clients], [c["total_rub"] for c in clients],
                   color="#4C78A8")
            ax.set_ylabel("RUB")
            _rub_axis(ax)
            ax.set_title("Клиенты по сумме на счетах (в рублях)")
            ax.tick_params(axis="x", rotation=30)
            ax.grid(axis="y", alpha=0.3)
        else:
            self._no_data(ax)
        self._finish(fig, path)

    def _chart_line(self, path, client_id):
        fig, ax = plt.subplots(figsize=(10, 5))
        ledger = self._bank.get_ledger(client_id=client_id)
        title = (f"Движение баланса клиента {client_id}" if client_id else "Движение баланса банка") + " (в рублях)"
        if ledger:
            ledger.sort(key=lambda e: e["time"])
            steps, totals, running = [], [], 0.0
            for number, entry in enumerate(ledger, start=1):
                running += to_rub(entry["delta"], entry["currency"])
                steps.append(number)
                totals.append(round(running, 2))
            ax.step(steps, totals, where="post", color="#54A24B")
            ax.scatter(steps, totals, s=14, color="#54A24B")
            # по оси X - номера операций (иначе всё сливается в одну точку), подписи - время
            gap = max(1, len(steps) // 7)
            marks = [m for m in steps[::gap] if steps[-1] - m >= gap // 2 + 1] + [steps[-1]]
            ax.set_xticks(marks)
            ax.set_xticklabels([f"{m}\n{ledger[m - 1]['time']:%d.%m %H:%M}" for m in marks], fontsize=8)
            ax.set_xlabel("номер операции и время")
            ax.set_ylabel("RUB")
            _rub_axis(ax)
            ax.grid(alpha=0.3)
        else:
            self._no_data(ax)
        ax.set_title(title)
        self._finish(fig, path)

    def _chart_risk(self, path):
        fig, ax = plt.subplots(figsize=(6, 4.5))
        by_level = self.risk_report()["by_level"]
        colors = {"low": "#54A24B", "medium": "#F58518", "high": "#E45756"}
        ax.bar(list(by_level), list(by_level.values()), color=[colors[k] for k in by_level])
        ax.set_title("Операции по уровням риска")
        ax.set_ylabel("штук")
        ax.grid(axis="y", alpha=0.3)
        self._finish(fig, path)