import hashlib
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

import requests

BASE_URL = "https://filings.xbrl.org"


def parse_filing(item: dict) -> dict:
    attrs = item["attributes"]
    json_url = attrs["json_url"]
    return {
        "filing_id": item["id"],
        "lei": attrs["fxo_id"].split("-")[0],
        "period_end": attrs["period_end"],
        "url": BASE_URL + json_url if json_url else None,
        "error_count": attrs["error_count"],
    }


def load_manifest(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open() as f:
        return {json.loads(line)["filing_id"] for line in f if line.strip()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def append_manifest(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def iter_filings(session, country: str = "DK", page_size: int = 1000, delay: float = 1.0):
    url = f"{BASE_URL}/api/filings"
    params = {"page[size]": page_size, "filter[country]": country}
    while url:
        response = session.get(url, params=params, timeout=30)
        response.raise_for_status()
        page = response.json()
        yield from page["data"]
        url = page["links"].get("next")
        params = None
        if url:
            time.sleep(delay)


def is_wanted(record: dict) -> bool:
    return (
        record["url"] is not None
        and record["error_count"] == 0
        and (record["period_end"] or "")[:4] in {"2024", "2025"}
    )


def download_file(session, url: str, dest: Path, retries: int = 4, sleep=time.sleep) -> None:
    for attempt in range(retries):
        try:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            status = getattr(exc.response, "status_code", None)
            permanent = status is not None and 400 <= status < 500 and status != 429
            if permanent or attempt == retries - 1:
                raise
            sleep(2**attempt)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(response.content)
    tmp.replace(dest)


def run(
    session,
    landing_dir: Path,
    ingest_date: str,
    delay: float = 1.0,
    sleep=time.sleep,
) -> dict:
    esef_dir = landing_dir / "esef"
    manifest_path = esef_dir / "manifest.jsonl"
    out_dir = esef_dir / f"ingest_date={ingest_date}"
    seen = load_manifest(manifest_path)
    counts = {"new": 0, "skipped": 0, "failed": 0}

    for item in iter_filings(session, delay=delay):
        record = parse_filing(item)
        if not is_wanted(record):
            continue
        if record["filing_id"] in seen:
            counts["skipped"] += 1
            continue

        name = f"{record['lei']}_{record['period_end']}_{record['filing_id']}.json"
        dest = out_dir / name
        try:
            download_file(session, record["url"], dest, sleep=sleep)
        except requests.RequestException as exc:
            print(f"failed: {record['filing_id']} {exc}", file=sys.stderr)
            counts["failed"] += 1
            continue

        append_manifest(
            manifest_path,
            {
                "filing_id": record["filing_id"],
                "lei": record["lei"],
                "period_end": record["period_end"],
                "url": record["url"],
                "sha256": sha256_file(dest),
                "downloaded_at": datetime.now(UTC).isoformat(),
            },
        )
        counts["new"] += 1
        sleep(delay)

    return counts


def main() -> None:
    with requests.Session() as session:
        counts = run(session, Path("data/landing"), date.today().isoformat())
    print(f"new={counts['new']} skipped={counts['skipped']} failed={counts['failed']}")


if __name__ == "__main__":
    main()
