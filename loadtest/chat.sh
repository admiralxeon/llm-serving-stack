#!/usr/bin/env bash
# One chat request through the gateway: APP_KEY=<key> bash loadtest/chat.sh "your question"
# Prints the HTTP status, which model answered and the time taken, then the answer.
question=${1:-Say hello.}
body=$(python -c 'import json,sys; print(json.dumps({"model":"chat","max_tokens":60,"messages":[{"role":"user","content":sys.argv[1]}]}))' "$question")
out=$(mktemp)
meta=$(curl -s -o "$out" -w '%{http_code} %{time_total}' localhost:4000/v1/chat/completions \
  -H "Authorization: Bearer $APP_KEY" -H "Content-Type: application/json" -d "$body")
python - "$out" $meta <<'PY'
import json, sys
path, status, seconds = sys.argv[1], sys.argv[2], float(sys.argv[3])
reply = json.load(open(path, encoding="utf-8"))
if status == "200":
    print(f"HTTP {status}  model={reply['model']}  time={seconds:.2f}s")
    print(reply["choices"][0]["message"]["content"].strip())
else:
    print(f"HTTP {status}  time={seconds:.2f}s")
PY
rm -f "$out"
