from __future__ import annotations

import argparse
import csv
import os
import sqlite3
from pathlib import Path


APP_HOME = Path(os.getenv("MINSAENG100_HOME", Path(__file__).resolve().parents[1]))
DB_PATH = Path(os.getenv("MINSAENG100_DB", APP_HOME / "data" / "minsaeng100.sqlite"))


def blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def to_int(value: str | None) -> int | None:
    value = blank_to_none(value)
    return int(value) if value is not None else None


def to_float(value: str | None) -> float | None:
    value = blank_to_none(value)
    return float(value) if value is not None else None


def import_credit(path: Path) -> None:
    with sqlite3.connect(DB_PATH) as conn, path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            conn.execute(
                """
                INSERT INTO manual_credit_guarantee_monthly (
                    base_month, guarantee_supply_amount_krw, guarantee_supply_count,
                    guarantee_balance_krw, source_org, source_file_name,
                    input_user, input_date, note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(base_month) DO UPDATE SET
                    guarantee_supply_amount_krw=excluded.guarantee_supply_amount_krw,
                    guarantee_supply_count=excluded.guarantee_supply_count,
                    guarantee_balance_krw=excluded.guarantee_balance_krw,
                    source_org=excluded.source_org,
                    source_file_name=excluded.source_file_name,
                    input_user=excluded.input_user,
                    input_date=excluded.input_date,
                    note=excluded.note,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    row["base_month"],
                    to_int(row.get("guarantee_supply_amount_krw")),
                    to_int(row.get("guarantee_supply_count")),
                    to_int(row.get("guarantee_balance_krw")),
                    row["source_org"],
                    blank_to_none(row.get("source_file_name")),
                    row["input_user"],
                    row["input_date"],
                    blank_to_none(row.get("note")),
                ),
            )


def import_policy(path: Path) -> None:
    with sqlite3.connect(DB_PATH) as conn, path.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            amount = to_int(row.get("cumulative_support_amount_krw"))
            total = to_int(row.get("total_plan_amount_krw"))
            execution_rate = to_float(row.get("execution_rate_pct"))
            if execution_rate is None and amount is not None and total:
                execution_rate = round(amount / total * 100, 2)
            conn.execute(
                """
                INSERT INTO manual_policy_fund_monthly (
                    base_month, program_name, total_plan_amount_krw,
                    cumulative_support_amount_krw, cumulative_support_count,
                    execution_rate_pct, source_org, source_url, source_file_name,
                    input_user, input_date, note, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(base_month) DO UPDATE SET
                    program_name=excluded.program_name,
                    total_plan_amount_krw=excluded.total_plan_amount_krw,
                    cumulative_support_amount_krw=excluded.cumulative_support_amount_krw,
                    cumulative_support_count=excluded.cumulative_support_count,
                    execution_rate_pct=excluded.execution_rate_pct,
                    source_org=excluded.source_org,
                    source_url=excluded.source_url,
                    source_file_name=excluded.source_file_name,
                    input_user=excluded.input_user,
                    input_date=excluded.input_date,
                    note=excluded.note,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    row["base_month"],
                    row["program_name"],
                    total,
                    amount,
                    to_int(row.get("cumulative_support_count")),
                    execution_rate,
                    row["source_org"],
                    blank_to_none(row.get("source_url")),
                    blank_to_none(row.get("source_file_name")),
                    row["input_user"],
                    row["input_date"],
                    blank_to_none(row.get("note")),
                ),
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["credit", "policy"])
    parser.add_argument("csv_path")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise SystemExit(f"DB not found: {DB_PATH}. Run scripts/init_db.py first.")

    path = Path(args.csv_path)
    if args.kind == "credit":
        import_credit(path)
    else:
        import_policy(path)
    print(f"imported {args.kind}: {path}")


if __name__ == "__main__":
    main()

