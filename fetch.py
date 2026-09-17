"""
fetch.py — the conductor. Run this and the whole pipeline happens.

    python scripts/fetch.py

WHAT IT DOES, IN ORDER
----------------------
1. Read config/sources.yaml to find out which sources to check.
2. Ask each collector for its current jobs.
3. Normalise them (seniority buckets, tidy locations).
4. Merge with what we already had, so we can tell new from old.
5. Write data/jobs.json and data/jobs.csv.

THE MERGE STEP IS THE IMPORTANT ONE
-----------------------------------
A naive version would overwrite the file with whatever it scraped today. Then
you'd have no idea what's new, and any posting that disappeared would vanish
from history. Instead we keep a running record and stamp each job with
first_seen and last_seen. That gives you, for free:

  - "new this week" (first_seen is within the last 7 days) → your Substack
  - "recently closed" (last_seen is old) → useful signal about hiring cycles
  - a full audit trail, because git stores every past version of the file
"""

from __future__ import annotations

import csv
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# Make sure Python can find the `collectors` package next to this file.
sys.path.insert(0, str(Path(__file__).parent))

from collectors import COLLECTORS           # noqa: E402
from normalise import normalise             # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.yaml"
DATA_DIR = ROOT / "data"
JOBS_JSON = DATA_DIR / "jobs.json"
JOBS_CSV = DATA_DIR / "jobs.csv"

TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

# Jobs we haven't seen in a listing for this many days get dropped, so the
# file doesn't grow forever. 120 days keeps a useful history without bloat.
RETENTION_DAYS = 120


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_existing() -> dict[str, dict]:
    """Read the jobs we already know about, keyed by id for fast lookup."""
    if not JOBS_JSON.exists():
        return {}
    with open(JOBS_JSON, "r", encoding="utf-8") as fh:
        records = json.load(fh)
    return {r["id"]: r for r in records}


def collect_all(config: dict) -> list[dict]:
    """Run every enabled source. One failing source must not kill the run."""
    results: list[dict] = []

    for source in config.get("sources", []):
        if not source.get("enabled", True):
            continue

        source_type = source.get("type")
        collector_class = COLLECTORS.get(source_type)

        if collector_class is None:
            print(f"  ! unknown source type '{source_type}', skipping")
            continue

        label = source.get("name", source_type)
        print(f"  → {label} ...", end=" ", flush=True)

        try:
            collector = collector_class(source.get("config", {}))
            jobs = collector.fetch()
            results.extend(job.to_dict() for job in jobs)
            print(f"{len(jobs)} jobs")
        except Exception as exc:
            # Deliberately broad: one broken website should not stop the
            # other nine sources from updating. We print the traceback so
            # the GitHub Actions log tells you exactly what broke.
            print(f"FAILED ({exc.__class__.__name__}: {exc})")
            traceback.print_exc()

    return results


def merge(existing: dict[str, dict], fresh: list[dict]) -> list[dict]:
    """Combine today's scrape with the historical record."""
    merged = dict(existing)      # start from what we had
    new_count = 0

    for job in fresh:
        job = normalise(job)
        job_id = job["id"]

        if job_id in merged:
            # Seen before: keep the original first_seen, refresh everything else.
            previous = merged[job_id]
            job["first_seen"] = previous.get("first_seen", TODAY)
            job["last_seen"] = TODAY
            # Preserve a manual override if you ever hand-correct a record.
            if previous.get("seniority_manual"):
                job["seniority"] = previous["seniority_manual"]
                job["seniority_manual"] = previous["seniority_manual"]
        else:
            job["first_seen"] = TODAY
            job["last_seen"] = TODAY
            new_count += 1

        merged[job_id] = job

    # Drop anything that hasn't appeared in a listing for a long time.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    kept = [j for j in merged.values() if (j.get("last_seen") or "") >= cutoff]

    print(f"\n  {new_count} new, {len(kept)} total after retention cutoff {cutoff}")

    # Sort newest first so the file is readable and git diffs stay sane.
    kept.sort(key=lambda j: (j.get("first_seen") or "", j.get("title") or ""), reverse=True)
    return kept


def write_outputs(jobs: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # The `raw` field is big and only useful for debugging — strip it from
    # what we publish, or the JSON file becomes megabytes.
    public = []
    for job in jobs:
        slim = {k: v for k, v in job.items() if k != "raw"}
        public.append(slim)

    with open(JOBS_JSON, "w", encoding="utf-8") as fh:
        json.dump(public, fh, indent=2, ensure_ascii=False)

    # A CSV as well, because sometimes you just want to open it in Excel.
    columns = [
        "id", "title", "organisation", "seniority", "contract_type",
        "city", "country", "date_posted", "deadline", "first_seen",
        "last_seen", "grade", "source", "url",
    ]
    with open(JOBS_CSV, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(public)

    # The website reads its own copy from the docs/ folder. GitHub Pages only
    # publishes what is inside docs/, so anything the page links to has to
    # live there too — including the CSV download.
    site_dir = ROOT / "docs"
    site_dir.mkdir(parents=True, exist_ok=True)

    with open(site_dir / "data.json", "w", encoding="utf-8") as fh:
        json.dump(
            {"generated": TODAY, "count": len(public), "jobs": public},
            fh, ensure_ascii=False, separators=(",", ":"),
        )

    with open(site_dir / "jobs.csv", "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(public)

    print(f"  wrote {JOBS_JSON.name}, {JOBS_CSV.name}, docs/data.json, docs/jobs.csv")


def main() -> int:
    print(f"Run started {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

    config = load_config()
    existing = load_existing()
    print(f"Loaded {len(existing)} known jobs. Collecting:\n")

    fresh = collect_all(config)

    if not fresh:
        print("\n  No jobs collected. Not overwriting existing data.")
        return 1        # a non-zero exit code makes the Action show as failed

    merged = merge(existing, fresh)
    write_outputs(merged)
    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
