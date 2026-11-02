# Load test results

| Run | Target | Users | Requests | Errors | TTFT p50 (ms) | TTFT p95 (ms) | Latency p50 (s) | Latency p95 (s) | Output tokens/s | Tokens per answer | Answered by |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| baseline | vllm | 1 | 58 | 0 | 20 | 27 | 2.03 | 2.20 | 96 | 199 | qwen2.5-1.5b (58) |
| baseline | vllm | 8 | 408 | 0 | 46 | 67 | 2.30 | 2.42 | 678 | 200 | qwen2.5-1.5b (408) |
| baseline | vllm | 32 | 809 | 0 | 2440 | 2621 | 4.80 | 5.18 | 1298 | 199 | qwen2.5-1.5b (809) |
| baseline | gateway | 1 | 58 | 0 | 77 | 85 | 2.07 | 2.15 | 96 | 199 | chat (58) |
| baseline | gateway | 8 | 414 | 0 | 76 | 122 | 2.32 | 2.46 | 676 | 199 | chat (414) |
| baseline | gateway | 32 | 821 | 0 | 2407 | 2640 | 4.78 | 5.05 | 1316 | 199 | chat (821) |
| seqs=32 | vllm | 32 | 1408 | 0 | 59 | 127 | 2.65 | 3.08 | 2303 | 199 | qwen2.5-1.5b (1408) |
| seqs=8 | vllm | 32 | 442 | 0 | 6814 | 7373 | 9.03 | 9.70 | 684 | 199 | qwen2.5-1.5b (442) |
