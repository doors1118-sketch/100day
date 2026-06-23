from __future__ import annotations

import argparse
import os
import sys
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx


BASE_URL = "https://ecos.bok.or.kr/api"


@dataclass(frozen=True)
class EcosCall:
    label: str
    path: str


def build_url(api_key: str, service: str, start: int, end: int, *parts: str) -> str:
    escaped = [urllib.parse.quote(str(p).strip("/"), safe="") for p in parts]
    return f"{BASE_URL}/{service}/{api_key}/json/kr/{start}/{end}/" + "/".join(escaped)


def request_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def print_result(label: str, data: dict[str, Any], max_rows: int = 8) -> None:
    print(f"\n## {label}")
    if "RESULT" in data:
        print(data["RESULT"])
        return

    key = next(iter(data.keys()), None)
    if not key:
        print("empty response")
        return

    payload = data[key]
    rows = payload.get("row", [])
    print("list_total_count:", payload.get("list_total_count"))
    print("rows:", len(rows))
    for row in rows[:max_rows]:
        print(row)
    if len(rows) > max_rows:
        print("...")
        for row in rows[-3:]:
            print(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check ECOS regional personal credit card tables.")
    parser.add_argument("--key", default=os.getenv("ECOS_API_KEY"), help="ECOS API key. Defaults to ECOS_API_KEY env var.")
    parser.add_argument("--from", dest="start_time", default="202501", help="Start period, e.g. 202501")
    parser.add_argument("--to", dest="end_time", default="202612", help="End period, e.g. 202612")
    args = parser.parse_args()

    if not args.key:
        print("ECOS API key is required. Set ECOS_API_KEY or pass --key.", file=sys.stderr)
        return 2

    api_key = args.key.strip()

    calls = [
        EcosCall(
            "StatisticItemList 043Y070",
            build_url(api_key, "StatisticItemList", 1, 100, "043Y070"),
        ),
        EcosCall(
            "StatisticItemList 601Y002",
            build_url(api_key, "StatisticItemList", 1, 100, "601Y002"),
        ),
        EcosCall(
            "StatisticSearch 043Y070 B/1000/TOT MM",
            build_url(api_key, "StatisticSearch", 1, 100, "043Y070", "MM", args.start_time, args.end_time, "B", "1000", "TOT"),
        ),
        EcosCall(
            "StatisticSearch 043Y070 B/1000/TOT M",
            build_url(api_key, "StatisticSearch", 1, 100, "043Y070", "M", args.start_time, args.end_time, "B", "1000", "TOT"),
        ),
        EcosCall(
            "StatisticSearch 601Y002 Busan all",
            build_url(api_key, "StatisticSearch", 1, 100, "601Y002", "M", args.start_time, args.end_time, "B"),
        ),
    ]

    for call in calls:
        print(f"\nURL: {call.path.replace(api_key, '<ECOS_API_KEY>')}")
        try:
            data = request_json(call.path)
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")
            continue
        print_result(call.label, data)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

