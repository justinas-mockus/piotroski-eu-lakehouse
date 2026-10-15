"""Count ESEF filings per country on filings.xbrl.org for the last two period ends.

Result and decision: docs/adr/002-country-choice.md. Run from a machine with internet
access (the Databricks workspace is blocked, see ADR-001). Pages through the full filings
list (page[size]=1000, about 20 s per page) and prints per-country totals:
filings, clean (error_count == 0), distinct entities, clean entities.
"""

import collections
import json
import sys
import time
import urllib.request

BASE = "https://filings.xbrl.org/api/filings?page[size]=1000"
YEARS = {"2024", "2025"}
HEADERS = {"Accept": "application/vnd.api+json"}


def fetch_all():
    url = BASE
    while url:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            page = json.load(resp)
        yield from page["data"]
        url = page["links"].get("next")
        time.sleep(1)


def entity_key(attrs):
    # json_url looks like "/EDRPOU-32033791/2020-12-31/..."; first segment is the entity id
    return attrs["json_url"].lstrip("/").split("/")[0] if attrs.get("json_url") else None


def main():
    total = 0
    per_country = collections.defaultdict(
        lambda: {"filings": 0, "clean": 0, "entities": set(), "clean_entities": set()}
    )
    for row in fetch_all():
        total += 1
        a = row["attributes"]
        if (a.get("period_end") or "")[:4] not in YEARS:
            continue
        c = per_country[a["country"]]
        ent = entity_key(a)
        c["filings"] += 1
        c["entities"].add(ent)
        if a.get("error_count") == 0:
            c["clean"] += 1
            c["clean_entities"].add(ent)

    print(f"total filings scanned: {total}")
    print(f"{'country':8}{'filings':>9}{'clean':>8}{'entities':>10}{'clean_ent':>11}")
    for country, c in sorted(per_country.items(), key=lambda kv: (-kv[1]["clean"], kv[0])):
        print(
            f"{country:8}{c['filings']:>9}{c['clean']:>8}"
            f"{len(c['entities']):>10}{len(c['clean_entities']):>11}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
