"""Backpressure test for /ask: N clients call it in a loop for a fixed time.

A client that gets 429 waits for Retry-After, as a well-behaved caller should.
Usage: .venv/Scripts/python loadtest/rag_burst.py <clients> <seconds> <label>
"""
import json
import statistics
import sys
import threading
import time
from collections import Counter
from pathlib import Path
from random import choice

import requests

URL = "http://localhost:8080/ask"
QUESTIONS = [
    "What are the main components of this system?",
    "What phases does the roadmap have?",
    "What data does the system store?",
    "Which external services does it connect to?",
]
RESULTS_FILE = Path(__file__).resolve().parent.parent / "results" / "RAG_BACKPRESSURE.md"

clients, seconds, label = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
accepted = []
rejected = []
statuses = Counter()
lock = threading.Lock()
stop_at = time.perf_counter() + seconds


def client():
    session = requests.Session()
    while time.perf_counter() < stop_at:
        start = time.perf_counter()
        try:
            response = session.post(URL, json={"question": choice(QUESTIONS)}, timeout=300)
            status = response.status_code
        except requests.RequestException:
            status = "connection error"
            response = None
        took = time.perf_counter() - start
        with lock:
            statuses[status] += 1
            (accepted if status == 200 else rejected).append(took)
        if status == 429:
            time.sleep(float(response.headers.get("Retry-After", 1)))


threads = [threading.Thread(target=client) for _ in range(clients)]
started = time.perf_counter()
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
elapsed = time.perf_counter() - started


def pct(values, p):
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * p / 100), len(ordered) - 1)] if ordered else 0


row = (
    f"| {label} | {clients} | {statuses[200]} | {statuses[429]} "
    f"| {sum(v for k, v in statuses.items() if k not in (200, 429))} "
    f"| {statuses[200] / elapsed:.1f} | {pct(accepted, 50):.2f} | {pct(accepted, 95):.2f} "
    f"| {statistics.median(rejected) * 1000 if rejected else 0:.0f} |"
)
print(row, json.dumps({str(k): v for k, v in statuses.items()}))
if not RESULTS_FILE.exists():
    RESULTS_FILE.write_text(
        "# RAG /ask backpressure test\n\n"
        "| MAX_IN_FLIGHT | Clients | 200 | 429 | Other errors | Answers/s | Accepted p50 (s) | Accepted p95 (s) | Rejected p50 (ms) |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
with RESULTS_FILE.open("a") as f:
    f.write(row + "\n")
