import hashlib
import json
from pathlib import Path

BASE_URL = "https://filings.xbrl.org"


def parse_filing(item: dict) -> dict:
    attrs = item["attributes"]
    return {
        "filing_id": item["id"],
        "lei": attrs["fxo_id"].split("-")[0],
        "period_end": attrs["period_end"],
        "url": BASE_URL + attrs["json_url"],
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
