import csv
import io
import json
import tempfile
import zipfile
from datetime import date
from pathlib import Path

import requests

LATEST_URL = "https://mapping.gleif.org/api/v2/isin-lei/latest"


def filter_rows(rows, leis: set[str]):
    for row in rows:
        if row["LEI"] in leis:
            yield row


def manifest_leis(path: Path) -> set[str]:
    with path.open() as f:
        return {json.loads(line)["lei"] for line in f if line.strip()}


def read_zip_csv(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        (name,) = zf.namelist()
        with zf.open(name) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            yield from csv.DictReader(text)


def write_csv(rows, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    count = 0
    with tmp.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["LEI", "ISIN"], lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    tmp.replace(dest)
    return count


def parse_latest(item: dict) -> dict:
    attrs = item["data"]["attributes"]
    return {
        "file_name": attrs["fileName"],
        "uploaded_at": attrs["uploadedAt"],
        "download_link": attrs["downloadLink"],
    }


def download_to(session, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    with session.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
    tmp.replace(dest)


def run(session, landing_dir: Path, ingest_date: str) -> dict:
    out_dir = landing_dir / "lei_isin" / f"ingest_date={ingest_date}"
    dest = out_dir / "lei_isin.csv"
    if dest.exists():
        return {"status": "skipped"}

    leis = manifest_leis(landing_dir / "esef" / "manifest.jsonl")
    response = session.get(LATEST_URL, timeout=30)
    response.raise_for_status()
    latest = parse_latest(response.json())

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "source.json").write_text(json.dumps(latest) + "\n")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / latest["file_name"]
        download_to(session, latest["download_link"], zip_path)
        rows = write_csv(filter_rows(read_zip_csv(zip_path), leis), dest)

    return {"status": "written", "leis": len(leis), "rows": rows}


def main() -> None:
    with requests.Session() as session:
        result = run(session, Path("data/landing"), date.today().isoformat())
    print(" ".join(f"{key}={value}" for key, value in result.items()))


if __name__ == "__main__":
    main()
