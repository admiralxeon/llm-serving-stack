> INVALID: these latencies were timed inside a container whose clock ran about 12-15% slow. Kept only as a record. Use RESULTS.md.

# Load test results

| Run | Target | Users | Requests | Errors | TTFT p50 (ms) | TTFT p95 (ms) | Latency p50 (s) | Latency p95 (s) | Output tokens/s | Tokens per answer | Answered by |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | vllm | 1 | 67 | 0 | 18 | 25 | 1.80 | 1.91 | 99 | 198 | qwen2.5-1.5b (67) |
| baseline | vllm | 8 | 488 | 0 | 32 | 55 | 1.99 | 2.06 | 719 | 199 | qwen2.5-1.5b (488) |
| baseline | vllm | 32 | 928 | 0 | 2152 | 2237 | 4.26 | 4.37 | 1311 | 199 | qwen2.5-1.5b (928) |
