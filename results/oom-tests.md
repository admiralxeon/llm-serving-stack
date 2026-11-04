# GPU memory failure tests

Model: Qwen2.5-1.5B FP16, vLLM v0.31.0, RTX 3060 Ti (8 GB) under Docker Desktop on Windows.
vLLM reported 6.96 of 8.0 GiB free at startup.

| `--gpu-memory-utilization` | Budget | Result | Error |
| --- | --- | --- | --- |
| 0.30 | 2.4 GiB | Would not start, restart loop | `ValueError: No available memory for the cache blocks` |
| 0.60 | 4.8 GiB | Works, 1.17 GiB KV cache | None |
| 0.85 | 6.8 GiB | Works, 3.17 GiB KV cache, about 7.6-7.7 GB of VRAM in use | None |
| 0.97 | 7.76 GiB | Would not start, restart loop | `ValueError: Free memory on device cuda:0 (6.96/8.0 GiB) on startup is less than desired GPU memory utilization` |

- During the 0.97 restart loop, `chat` through LiteLLM still returned 200 from Ollama.
- Both failures were fixed by setting a value between those limits and running `docker compose up -d vllm`.
- A real `torch.OutOfMemoryError` was NOT reproduced. With vLLM at 0.85, a second process allocated 2 GiB
  with about 600 MiB apparently free. VRAM in use then fell from 7581 to 5411 MiB and vLLM still answered.
  Windows appears to page GPU memory, so this test may behave differently on a Linux server.
