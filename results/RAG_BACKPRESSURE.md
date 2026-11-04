# RAG /ask backpressure test

| MAX_IN_FLIGHT | Clients | 200 | 429 | Other errors | Answers/s | Accepted p50 (s) | Accepted p95 (s) | Rejected p50 (ms) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8 | 32 | 225 | 1392 | 0 | 3.5 | 1.99 | 3.78 | 3 |
| 16 | 32 | 394 | 928 | 0 | 6.3 | 2.18 | 4.80 | 3 |
| 1000 | 32 | 474 | 0 | 0 | 7.3 | 3.78 | 6.26 | 0 |
