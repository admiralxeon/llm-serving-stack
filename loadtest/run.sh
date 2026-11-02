#!/usr/bin/env bash
# One load test run: loadtest/run.sh <vllm|gateway> <users> <label> [duration]
# Appends a row to results/RESULTS.md and prints vLLM's peak queue and KV cache use.
target=$1; users=$2; label=$3; duration=${4:-2m}
samples=$(mktemp)
( while :; do curl -s localhost:8000/metrics >> "$samples"; python -c "import time; time.sleep(3)"; done ) &
sampler=$!
PYTHONIOENCODING=utf-8 TARGET=$target LABEL=$label .venv/Scripts/locust -f loadtest/locustfile.py \
  --headless --only-summary --stop-timeout=120 -u "$users" -r "$users" -t "$duration" 2>&1 | grep -E "RESULT|Traceback"
kill $sampler 2>/dev/null
peak() { grep -E "^vllm:$1\{" "$samples" | awk -v m=0 '{ if ($2+0 > m) m = $2+0 } END { print m }'; }
echo "   peaks: running=$(peak num_requests_running) waiting=$(peak num_requests_waiting) kv_cache=$(peak kv_cache_usage_perc) preemptions_total=$(peak num_preemptions_total)"
rm -f "$samples"
