import argparse
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django


STAT_FIELDS = (
    "xact_commit",
    "xact_rollback",
    "blks_read",
    "blks_hit",
    "tup_returned",
    "tup_fetched",
    "deadlocks",
    "temp_bytes",
)


def read_database_stats():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT numbackends, xact_commit, xact_rollback, blks_read,
                   blks_hit, tup_returned, tup_fetched, deadlocks, temp_bytes
            FROM pg_stat_database
            WHERE datname = current_database()
            """
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL database statistics were unavailable.")
        return dict(zip(("numbackends", *STAT_FIELDS), row, strict=True))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sample PostgreSQL database counters during a load test."
    )
    parser.add_argument("--duration", type=int, default=60)
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if args.duration <= 0 or args.interval <= 0:
        parser.error("--duration and --interval must be positive.")
    return args


def main():
    args = parse_args()
    django.setup()
    previous = read_database_stats()
    writer = csv.writer(sys.stdout)
    writer.writerow(
        ["timestamp_utc", "numbackends"]
        + [f"{field}_delta" for field in STAT_FIELDS]
        + ["shared_buffer_hit_percent"]
    )
    sys.stdout.flush()

    deadline = time.monotonic() + args.duration
    while time.monotonic() < deadline:
        time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
        current = read_database_stats()
        deltas = {
            field: current[field] - previous[field]
            for field in STAT_FIELDS
        }
        block_total = deltas["blks_hit"] + deltas["blks_read"]
        hit_percent = (
            f"{100 * deltas['blks_hit'] / block_total:.2f}"
            if block_total
            else ""
        )
        writer.writerow(
            [
                datetime.now(timezone.utc).isoformat(),
                current["numbackends"],
                *[deltas[field] for field in STAT_FIELDS],
                hit_percent,
            ]
        )
        sys.stdout.flush()
        previous = current


if __name__ == "__main__":
    main()
