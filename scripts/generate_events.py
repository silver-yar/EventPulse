#!/usr/bin/env python3
"""EventPulse demo event generator.

Generates realistic events and POSTs them to the ingest endpoint, shaped to
stay inside the API Gateway usage plan (rate 100 rps / burst 200): a shared
token bucket gates aggregate throughput to --rate (default 90/s) across
--workers threads. 429 responses retry with backoff; 403 aborts.

Usage:
    .venv/bin/python scripts/generate_events.py --count 5000
    .venv/bin/python scripts/generate_events.py --dry-run 5    # print, no POST
"""

import argparse
import json
import os
import random
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import boto3

STACK = "eventpulse-dev"

EVENT_TYPES = ["page_view", "add_to_cart", "purchase", "error"]
TYPE_WEIGHTS = [60, 25, 10, 5]

PRODUCTS = [42, 7, 1337, 9, 2048, 101, 77, 3, 555, 999]
URLS = ["/"] + [f"/products/{p}" for p in PRODUCTS] + ["/about", "/cart", "/checkout"]
ERROR_CODES = {
    "timeout": "request timed out upstream",
    "validation": "form validation failed",
    "payment": "card declined",
    "parse": "response parsing error",
}


class TokenBucket:
    """Thread-safe token bucket: aggregate --rate tokens/sec, burst --burst.

    The single bucket is shared by all workers, so aggregate throughput never
    exceeds --rate regardless of concurrency -- mirrors the usage-plan shape.
    """

    def __init__(self, rate: float, burst: int):
        self.rate = rate
        self.burst = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
            time.sleep(0.005)


def load_key(env_file: Path, cli_key: str | None) -> str:
    """API key from --key, API_KEY env, or scripts/.env (gitignored)."""
    if cli_key:
        return cli_key
    if os.environ.get("API_KEY"):
        return os.environ["API_KEY"]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("No API key: pass --key, set API_KEY, or write scripts/.env")


def resolve_endpoint() -> str:
    cf = boto3.client("cloudformation")
    outputs = cf.describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]
    return next(o["OutputValue"] for o in outputs if o["OutputKey"] == "ApiEndpoint")


class Scene:
    """Deterministic-ish event streams from small pools (seeded RNG)."""

    def __init__(self, rng: random.Random, days: int):
        self.rng = rng
        self.days = days
        self.users = [f"u_{i:04d}" for i in range(1, 501)]
        self.sessions: dict = {}
        self.now = datetime.now(timezone.utc)

    def build(self) -> dict:
        event_type = self.rng.choices(EVENT_TYPES, weights=TYPE_WEIGHTS)[0]
        user = self.rng.choice(self.users)
        session = self.sessions.get(user)
        if session is None or self.rng.random() < 0.3:
            session = str(uuid4())
            self.sessions[user] = session
        event = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "user_id": user,
            "session_id": session,
            "event_ts": (
                self.now - timedelta(seconds=self.rng.uniform(0, self.days * 86400))
            ).isoformat(),
        }
        if event_type == "page_view":
            event["properties"] = {"url": self.rng.choice(URLS)}
        elif event_type in ("add_to_cart", "purchase"):
            event["properties"] = {
                "product_id": self.rng.choice(PRODUCTS),
                "amount_usd": round(self.rng.uniform(5, 250), 2),
            }
        else:  # error
            code = self.rng.choice(list(ERROR_CODES))
            event["properties"] = {"error_code": code, "message": ERROR_CODES[code]}
        return event


def post(base_url: str, key: str, payload: dict, retries: int) -> tuple[int, bool, int]:
    """POST one event. Returns (status, ok, attempts_used_after_429s)."""
    data = json.dumps(payload).encode()
    used_retries = 0
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            base_url + "/events",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "x-api-key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, True, used_retries
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(1.0)  # tripwire; should never fire at 90/20
                used_retries += 1
                continue
            return e.code, False, used_retries
        except OSError:
            if attempt < retries:
                time.sleep(0.5)
                continue
            return 0, False, used_retries
    return 429, False, used_retries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5000)
    parser.add_argument("--rate", type=float, default=90)
    parser.add_argument("--burst", type=int, default=20)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", type=int, default=0)
    parser.add_argument("--endpoint")
    parser.add_argument("--key")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    scene = Scene(rng, args.days)

    if args.dry_run:
        for _ in range(args.dry_run):
            print(json.dumps(scene.build()))
        return 0

    key = load_key(Path(__file__).parent / ".env", args.key)
    base_url = args.endpoint or resolve_endpoint()
    bucket = TokenBucket(args.rate, args.burst)

    sent = failed = retried = 0
    failures: list = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        nonlocal sent, failed, retried
        payload = scene.build()
        bucket.acquire()
        status, ok, used = post(base_url, key, payload, retries=5)
        if status == 403:
            raise SystemExit(f"403 at event {i}: invalid API key - check scripts/.env")
        with lock:
            sent += 1 if ok else 0
            failed += 0 if ok else 1
            retried += used
            if not ok:
                failures.append((i, status, payload["event_id"]))
            if (sent + failed) % 500 == 0:
                print(f"progress: sent={sent} failed={failed}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(worker, range(args.count)))

    print(f"summary: sent={sent} failed={failed} retried={retried}")
    for item in failures[:5]:
        print("  failed:", item)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())