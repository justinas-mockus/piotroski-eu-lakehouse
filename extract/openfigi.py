import csv
import os
import time
from datetime import date
from pathlib import Path

import requests

MAPPING_URL = "https://api.openfigi.com/v3/mapping"
EXCH_CODE = "DC"  # Bloomberg exchange code for Nasdaq Copenhagen
ISIN_PREFIX = "DK"  # Danish equities on Copenhagen carry DK ISINs (ADR-008)
# Jobs per request: 100 with a free API key, 10 without (the docs also say 5; lower it on a 413).
BATCH_SIZE_KEY = 100
BATCH_SIZE_ANON = 10
FIELDS = ["lei", "isin", "figi", "ticker", "name", "exch_code", "security_type", "market_sector"]


def latest_lei_isin(landing_dir: Path) -> Path:
    files = sorted(landing_dir.glob("lei_isin/ingest_date=*/lei_isin.csv"))
    if not files:
        raise FileNotFoundError("no lei_isin.csv in landing; run extract.gleif_isin first")
    return files[-1]


def read_lei_by_isin(path: Path, prefix: str = ISIN_PREFIX) -> dict[str, str]:
    with path.open(newline="") as f:
        return {
            row["ISIN"]: row["LEI"] for row in csv.DictReader(f) if row["ISIN"].startswith(prefix)
        }


def batches(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def mapping_jobs(isins: list[str]) -> list[dict]:
    return [{"idType": "ID_ISIN", "idValue": isin, "exchCode": EXCH_CODE} for isin in isins]


def parse_results(isins: list[str], results: list[dict], lei_by_isin: dict[str, str]) -> list[dict]:
    rows = []
    for isin, result in zip(isins, results, strict=True):
        for item in result.get("data", []):
            rows.append(
                {
                    "lei": lei_by_isin[isin],
                    "isin": isin,
                    "figi": item.get("figi"),
                    "ticker": item.get("ticker"),
                    "name": item.get("name"),
                    "exch_code": item.get("exchCode"),
                    "security_type": item.get("securityType"),
                    "market_sector": item.get("marketSector"),
                }
            )
    return rows


def post_mapping(
    session, jobs: list[dict], headers: dict, retries: int = 4, sleep=time.sleep
) -> list[dict]:
    for attempt in range(retries):
        try:
            response = session.post(MAPPING_URL, json=jobs, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 413:
                raise RuntimeError(
                    f"batch of {len(jobs)} jobs too large; lower batch_size"
                ) from exc
            permanent = status is not None and 400 <= status < 500 and status != 429
            if permanent or attempt == retries - 1:
                raise
            sleep(5 * 2**attempt)
    raise AssertionError("unreachable")


def write_csv(rows: list[dict], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(dest)


def run(
    session,
    landing_dir: Path,
    ingest_date: str,
    api_key: str | None = None,
    batch_size: int | None = None,
    sleep=time.sleep,
) -> dict:
    dest = landing_dir / "openfigi" / f"ingest_date={ingest_date}" / "isin_ticker.csv"
    if dest.exists():
        return {"status": "skipped"}

    headers = {"X-OPENFIGI-APIKEY": api_key} if api_key else {}
    batch_size = batch_size or (BATCH_SIZE_KEY if api_key else BATCH_SIZE_ANON)
    delay = 0.3 if api_key else 2.5  # 25 requests per 6 s with a key, per minute without

    lei_by_isin = read_lei_by_isin(latest_lei_isin(landing_dir))
    isins = sorted(lei_by_isin)
    rows = []
    for i, chunk in enumerate(batches(isins, batch_size)):
        if i:
            sleep(delay)
        results = post_mapping(session, mapping_jobs(chunk), headers, sleep=sleep)
        rows.extend(parse_results(chunk, results, lei_by_isin))

    write_csv(rows, dest)
    return {
        "status": "written",
        "isins_sent": len(isins),
        "isins_matched": len({row["isin"] for row in rows}),
        "leis_sent": len(set(lei_by_isin.values())),
        "leis_matched": len({row["lei"] for row in rows}),
        "rows": len(rows),
    }


def main() -> None:
    api_key = os.environ.get("OPENFIGI_API_KEY")
    with requests.Session() as session:
        result = run(session, Path("data/landing"), date.today().isoformat(), api_key=api_key)
    print(" ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
