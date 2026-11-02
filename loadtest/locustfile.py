"""Load test for the chat API. Each simulated user sends a streaming request,
waits for the full answer, then immediately sends the next one.

Locust's own table times only the response headers on a streaming call, so this
file measures time to first token and full latency itself. One row per run is
appended to results/RESULTS.md (except when LABEL=smoke).

Run this on Windows, not in a container: the clock inside Docker Desktop's WSL2 VM
ran about 12-15% slow on this machine, which made latencies read too low.
"""
import json
import os
import random
import time
from collections import Counter
from pathlib import Path

from locust import HttpUser, constant, events, task

TARGET = os.environ.get("TARGET", "vllm")
LABEL = os.environ.get("LABEL", "baseline")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "200"))
# Keep generating to MAX_TOKENS even if the model wants to stop. vLLM only (not via LiteLLM).
IGNORE_EOS = os.environ.get("IGNORE_EOS") == "1"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_FILE = PROJECT_ROOT / "results" / "RESULTS.md"
SECRETS = dict(
    line.split("=", 1)
    for line in (PROJECT_ROOT / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)

TARGETS = {
    # Straight to vLLM: measures the model server alone.
    "vllm": ("http://localhost:8000", SECRETS["VLLM_API_KEY"], "qwen2.5-1.5b"),
    # Through LiteLLM: the difference from "vllm" is the gateway's overhead.
    "gateway": ("http://localhost:4000", SECRETS["LITELLM_MASTER_KEY"], "chat"),
}
HOST, API_KEY, MODEL = TARGETS[TARGET]
MODEL = os.environ.get("MODEL", MODEL)

PROMPTS = [
    "Explain in about 150 words how a power rectifier converts AC to DC.",
    "Explain in about 150 words why GPUs are faster than CPUs for matrix maths.",
    "Explain in about 150 words what a database index is and when to avoid one.",
    "Explain in about 150 words how a load balancer decides where to send traffic.",
]

ttfts = []
latencies = []
output_tokens = 0
answered_by = Counter()
errors = Counter()
started_at = None
last_finished_at = None


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * pct / 100), len(ordered) - 1)]


class ChatUser(HttpUser):
    host = HOST
    # No pause between requests: "users" here means requests in flight.
    wait_time = constant(0)

    @task
    def chat(self):
        global output_tokens, last_finished_at
        # A unique start stops vLLM's prefix cache from making repeat prompts look fast.
        prompt = f"Ticket {random.randint(0, 10**9)}. {random.choice(PROMPTS)}"
        body = {
            "model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": MAX_TOKENS,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if IGNORE_EOS:
            body["ignore_eos"] = True
        start = time.perf_counter()
        first_token_at = None
        usage_tokens = 0
        model_seen = None
        with self.client.post(
            "/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {API_KEY}"},
            stream=True,
            catch_response=True,
            timeout=300,
            name="chat (headers only)",
        ) as response:
            if response.status_code != 200:
                errors[str(response.status_code)] += 1
                response.failure(f"HTTP {response.status_code}")
                return
            try:
                for line in response.iter_lines():
                    if not line.startswith(b"data: ") or line == b"data: [DONE]":
                        continue
                    chunk = json.loads(line[6:])
                    if "error" in chunk:
                        raise RuntimeError(str(chunk["error"])[:100])
                    model_seen = chunk.get("model", model_seen)
                    if chunk.get("usage"):
                        usage_tokens = chunk["usage"]["completion_tokens"]
                    choices = chunk.get("choices") or []
                    if first_token_at is None and choices and choices[0].get("delta", {}).get("content"):
                        first_token_at = time.perf_counter()
            except Exception as exc:
                errors[type(exc).__name__] += 1
                response.failure(str(exc))
                return
            if first_token_at is None:
                errors["no tokens"] += 1
                response.failure("stream ended with no tokens")
                return
            ttfts.append((first_token_at - start) * 1000)
            latencies.append(time.perf_counter() - start)
            output_tokens += usage_tokens
            answered_by[model_seen] += 1
            last_finished_at = time.perf_counter()
            response.success()


@events.test_start.add_listener
def on_start(environment, **_):
    global started_at
    started_at = time.perf_counter()


@events.test_stop.add_listener
def on_stop(environment, **_):
    users = environment.parsed_options.num_users
    error_text = ", ".join(f"{k}: {v}" for k, v in errors.items()) or "0"
    if not latencies:
        print(f"\nRESULT {LABEL}: no successful requests. Errors: {error_text}")
        return
    elapsed = last_finished_at - started_at
    models = ", ".join(f"{k} ({v})" for k, v in answered_by.items())
    row = (
        f"| {LABEL} | {TARGET} | {users} | {len(latencies)} | {error_text} "
        f"| {percentile(ttfts, 50):.0f} | {percentile(ttfts, 95):.0f} "
        f"| {percentile(latencies, 50):.2f} | {percentile(latencies, 95):.2f} "
        f"| {output_tokens / elapsed:.0f} | {output_tokens / len(latencies):.0f} | {models} |"
    )
    print("\nRESULT " + row)
    if LABEL == "smoke":
        return
    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text(
            "# Load test results\n\n"
            "| Run | Target | Users | Requests | Errors | TTFT p50 (ms) | TTFT p95 (ms) "
            "| Latency p50 (s) | Latency p95 (s) | Output tokens/s | Tokens per answer | Answered by |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
        )
    with RESULTS_FILE.open("a") as f:
        f.write(row + "\n")
