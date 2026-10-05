import csv
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

from demo import run_demo
from src.bank import Bank
from src.exceptions import ClientNotFoundError, InvalidOperationError
from src.report_builder import ReportBuilder

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def section(title):
    print(f"\n=== {title} ===")


def expect_error(error_type, func, label):
    try:
        func()
    except error_type as e:
        print(f"{label}: {type(e).__name__}: {e}")
        return
    raise AssertionError(f"{label}: ошибка не возникла")


def main():
    # готовые данные берём из демо: 8 клиентов, 14 счетов, 38 транзакций
    demo = run_demo(output_dir=os.path.join(ROOT, "output"), verbose=False)
    bank, queue = demo.bank, demo.queue
    builder = ReportBuilder(bank, queue)
    out_dir = os.path.join(ROOT, "output", "reports")
    os.makedirs(out_dir, exist_ok=True)

    section("1. Отчёт по клиенту")
    client = builder.client_report("c-anna")
    print(builder.to_text(client))
    assert client["type"] == "client" and client["client"]["full_name"] == "Анна Петрова"
    assert len(client["accounts"]) == 2 and len(client["transactions"]) == 9
    assert client["total_rub"] == 467_000.0
    # журнал движения денег сходится с остатками: сумма изменений = текущая стоимость
    for account in client["accounts"]:
        moved = sum(e["delta"] for e in bank.get_ledger(account_id=account["account_id"]))
        assert round(moved, 2) == round(account["total_value"], 2)

    section("2. Отчёт по банку")
    bank_report = builder.bank_report()
    print(builder.to_text(bank_report))
    assert bank_report["clients_count"] == 8 and bank_report["accounts_count"] == 14
    assert bank_report["total_rub"] == demo.total_rub() == 3_537_899.8
    assert [c["full_name"] for c in bank_report["top_clients"]] == \
        ["Егор Фролов", "Вера Соколова", "Анна Петрова"]
    assert bank_report["transactions"]["by_status"] == {"completed": 29, "failed": 8, "cancelled": 1}
    assert sum(t["count"] for t in bank_report["accounts_by_type"].values()) == 14

    section("3. Отчёт по рискам")
    risk_report = builder.risk_report()
    print(builder.to_text(risk_report))
    assert risk_report["blocked_count"] == 3 and risk_report["by_level"]["high"] == 3
    assert risk_report["client_profiles"][0]["client_id"] == "c-egor"
    assert all(s["level"] != "low" for s in risk_report["suspicious_operations"])

    section("4. Экспорт в JSON")
    json_paths = {}
    for name, report in (("client", client), ("bank", bank_report), ("risk", risk_report)):
        path = builder.export_to_json(report, os.path.join(out_dir, f"{name}_report.json"))
        json_paths[name] = path
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)                 # файл читается обратно как обычный JSON
        assert loaded["type"] == name
        print(f"{name}: {os.path.getsize(path)} байт, ключи: {list(loaded)[:5]}...")
    with open(json_paths["bank"], encoding="utf-8") as f:
        assert json.load(f)["total_rub"] == 3_537_899.8
    assert "Анна Петрова" in builder.to_json(client), "кириллица не должна превращаться в \\u-коды"

    section("5. Экспорт в CSV")
    checks = [
        (client, "client_accounts.csv", None, 2),
        (client, "client_transactions.csv", "transactions", 9),
        (bank_report, "bank_accounts.csv", None, 14),
        (risk_report, "risk_suspicious.csv", None, len(risk_report["suspicious_operations"])),
    ]
    for report, file_name, table, expected in checks:
        path = builder.export_to_csv(report, os.path.join(out_dir, file_name), section=table)
        with open(path, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
        assert len(rows) == expected, (file_name, len(rows), expected)
        print(f"{file_name}: строк {len(rows)}, колонки {list(rows[0])[:4]}...")
    with open(os.path.join(out_dir, "bank_accounts.csv"), encoding="utf-8-sig", newline="") as f:
        owners = {r["owner"] for r in csv.DictReader(f, delimiter=";")}
    assert "Егор Фролов" in owners

    section("6. Графики")
    paths = builder.save_charts(out_dir)
    paths.update({f"{k}_egor": v for k, v in builder.save_charts(out_dir, client_id="c-egor").items()
                  if k in ("pie", "line")})
    for name, path in paths.items():
        assert os.path.getsize(path) > 5_000, f"график {name} слишком маленький"
        with open(path, "rb") as f:
            assert f.read(8) == PNG_SIGNATURE, f"{path} - не PNG"
        print(f"{name:<9} {os.path.basename(path):<32} {os.path.getsize(path):>7} байт")

    section("7. Пустой банк: отчёты и графики не падают")
    empty_bank = Bank("Пустой банк")
    empty = ReportBuilder(empty_bank)
    report = empty.bank_report()
    assert report["accounts_count"] == 0 and report["total_rub"] == 0
    assert "Клиентов: 0" in empty.to_text(report)
    empty_paths = empty.save_charts(os.path.join(out_dir, "empty"))
    assert all(os.path.getsize(p) > 0 for p in empty_paths.values())
    print("Пустой банк: 4 графика сохранены, отчёт собран")

    section("8. Некорректные данные отклоняются")
    expect_error(ClientNotFoundError, lambda: builder.client_report("c-nobody"), "несуществующий клиент")
    expect_error(InvalidOperationError, lambda: ReportBuilder("не банк"), "вместо банка строка")
    expect_error(InvalidOperationError, lambda: builder.to_text({"type": "oops"}), "чужой словарь вместо отчёта")
    expect_error(InvalidOperationError, lambda: builder.export_to_json(client, ""), "пустой путь")
    expect_error(InvalidOperationError,
                 lambda: builder.export_to_csv(client, os.path.join(out_dir, "x.csv"), section="client"),
                 "раздел, который не таблица")
    expect_error(InvalidOperationError, lambda: builder.save_charts(""), "пустая папка для графиков")
    expect_error(ClientNotFoundError, lambda: builder.save_charts(out_dir, client_id="c-nobody"),
                 "график несуществующего клиента")

    print(f"\nВсе проверки пройдены. Файлы отчётов и графиков: {out_dir}")


if __name__ == "__main__":
    main()