# Private LLM Serving Stack

A small, working copy of a private LLM server: vLLM on the GPU, a LiteLLM gateway in front, a RAG app, load tests and monitoring. It runs from `docker compose up` on one RTX 3060 Ti (8 GB).

Every number here was measured on this machine, and each is one run unless stated otherwise. They show how the system behaves, not what a production server would do.

## Architecture

```
LAN clients ──► :4000 LiteLLM gateway ──► vLLM (GPU)      chat, primary
                 keys, RPM limits,    ├─► Ollama (CPU)    chat fallback, embeddings
                 timeouts, fallback   └─► Postgres        keys, usage logs

This PC only:
  :8080 RAG app ──► LiteLLM ("chat", "embed"); Postgres + pgvector (chunks)
  :9090 Prometheus ──► vLLM /metrics, GPU exporter (nvidia-smi)
  :3000 Grafana ──► Prometheus
  :8000 vLLM, :11434 Ollama, :5432 Postgres (debugging and benchmarks)
```

| Service | Image | Job |
| --- | --- | --- |
| vllm | `vllm/vllm-openai:v0.31.0` | Serves Qwen2.5-1.5B-Instruct on the GPU |
| ollama | `ollama/ollama:0.40.13` | CPU only: backup chat model and `nomic-embed-text` |
| ollama-pull | same as ollama | One-time job that downloads Ollama's models |
| litellm | `litellm/litellm-database:v1.105.7` | Gateway: per-app keys, RPM limits, timeouts, routing, fallback |
| postgres | `pgvector/pgvector:0.8.7-pg17-bookworm` | LiteLLM's records and the RAG vectors |
| gpu-exporter | `utkuozdemir/nvidia_gpu_exporter:1.16.0` | GPU metrics from `nvidia-smi` |
| prometheus | `prom/prometheus:v3.15.1` | Collects metrics, evaluates the alert |
| grafana | `grafana/grafana:13.1.9` | Dashboard, provisioned from files |
| rag | built from `rag/` | FastAPI: `/ingest`, `/ask`, `/search`, `/health` |

Only port 4000 is open to the LAN. vLLM's key is known only to LiteLLM, and each app gets its own LiteLLM key.

## Deploy

Requires Docker with GPU access. Check that first:

```bash
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Then:

```bash
cp .env.example .env   # set real values; LITELLM_MASTER_KEY must start with sk-
docker compose up -d
docker compose ps -a   # wait for healthy; ollama-pull should show Exited (0)
```

A restart with models already cached took 145 s to reach healthy. A first start also downloads about 3 GB of vLLM weights (320 s here) and the Ollama models, and Grafana's first start took several minutes.

The RAG app needs its own LiteLLM key, which can only be created once LiteLLM is running:

```bash
curl localhost:4000/key/generate -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{"key_alias":"rag-app","rpm_limit":6000,"models":["chat","embed"]}'
# put the returned key in .env as RAG_LITELLM_KEY, then:
docker compose up -d rag
```

Use it:

```bash
curl -F "file=@your.pdf" localhost:8080/ingest
curl localhost:8080/ask -H "Content-Type: application/json" -d '{"question":"..."}'
```

Grafana is at `localhost:3000` (user `admin`, password `GRAFANA_PASSWORD`), and the alert state is at `localhost:9090/alerts`.

To reach the gateway from other machines on Windows, allow port 4000 for the local subnet only, in PowerShell as Administrator:

```powershell
New-NetFirewallRule -DisplayName "LiteLLM 4000 (LAN only)" -Direction Inbound -Protocol TCP -LocalPort 4000 -RemoteAddress LocalSubnet -Action Allow -Profile Any
```

## Rollback

Image tags and the Hugging Face model revision are pinned, so nothing changes by accident.

| To roll back | Do this |
| --- | --- |
| vLLM, LiteLLM or another image | Change the tag in `docker-compose.yml` back, then `docker compose up -d <service>` |
| Model | Set `VLLM_MODEL` and `VLLM_REVISION` back, or remove them, then `docker compose up -d vllm` |
| vLLM settings | Remove the override (`VLLM_GPU_MEM`, `VLLM_MAX_SEQS`, `VLLM_MAX_LEN`), then `docker compose up -d vllm` |
| Gateway routing | Revert `litellm/config.yaml`, then `docker compose restart litellm` |

Switching models and settings was done repeatedly during testing. Going back to an older image tag was not tested. Check LiteLLM's release notes first, because it runs database migrations on start.

## OOM and memory troubleshooting

Start with `docker compose logs vllm` and `nvidia-smi`. A restart loop hides the root error, so read the first error, not the last.

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Free memory on device ... is less than desired GPU memory utilization` | The share asked for exceeds free VRAM (failed at 0.97 with 6.96 GiB free) | Lower `VLLM_GPU_MEM`, or free the VRAM other programs hold |
| `No available memory for the cache blocks` | Budget too small for weights plus KV cache (failed at 0.30) | Raise `VLLM_GPU_MEM`, or use a smaller or quantized model |
| Restart count climbing | `restart: unless-stopped` re-runs a bad config forever | Fix the config. Restarting won't help |
| Postgres "unhealthy" after the PC shut down without stopping the stack | Crash recovery (about 130 s here) | Wait for recovery. Its health check now allows 240 s to start |
| Latency spikes, no errors, KV cache near 100% | Preemption: vLLM is throwing out work to redo later | Lower `--max-num-seqs`, cap `max_tokens`, or add memory |
| `vllm:num_requests_waiting` stays high | More demand than slots | Raise `--max-num-seqs` while watching KV cache, or add capacity |

Measured limits for Qwen2.5-1.5B FP16 (details in `results/oom-tests.md`):

| `--gpu-memory-utilization` | Result | KV cache |
| --- | --- | --- |
| 0.30 | Won't start | None |
| 0.60 (default) | Works | 1.17 GiB, 43,984 tokens |
| 0.85 | Works, leaves about 500 MiB for Windows | 3.17 GiB |
| 0.97 | Won't start | None |

A runtime `torch.OutOfMemoryError` was **not** reproduced. On this Windows setup, a second program allocated 2 GiB when only about 600 MiB looked free, and vLLM kept answering. Expect different behaviour on a Linux server.

## Measured results

### Load tests

Locust runs on Windows, not in a container, because the Docker VM's clock ran about 12-15% slow here. Earlier runs affected by this are kept in `results/invalid-container-clock.md`. All rows are in `results/RESULTS.md`.

Answers of about 200 tokens, 16 slots, `max-model-len` 4096, 2-minute runs, 0 errors:

| Target | Users | TTFT p50 | TTFT p95 | Latency p50 | Latency p95 | Output tokens/s | Peak KV cache |
| --- | --- | --- | --- | --- | --- | --- | --- |
| vLLM | 1 | 20 ms | 27 ms | 2.03 s | 2.20 s | 96 | 0.5% |
| vLLM | 8 | 46 ms | 67 ms | 2.30 s | 2.42 s | 678 | 3.3% |
| vLLM | 32 | 2,440 ms | 2,621 ms | 4.80 s | 5.18 s | 1,298 | 5.8% |
| Gateway | 1 | 77 ms | 85 ms | 2.07 s | 2.15 s | 96 | 0.5% |
| Gateway | 8 | 76 ms | 122 ms | 2.32 s | 2.46 s | 676 | 3.1% |
| Gateway | 32 | 2,407 ms | 2,640 ms | 4.78 s | 5.05 s | 1,316 | 6.4% |

The gateway added about 57 ms to TTFT at 1 user and about 30 ms at 8. At 32 users the difference is lost in the queue wait.

`--max-num-seqs`, at 32 users:

| Slots | TTFT p50 | Latency p50 | Output tokens/s | Peak KV cache |
| --- | --- | --- | --- | --- |
| 8 | 6,814 ms | 9.03 s | 684 | 3.9% |
| 16 | 2,440 ms | 4.80 s | 1,298 | 5.8% |
| 32 | 59 ms | 2.65 s | 2,303 | 14.9% |

Long answers (exactly 2,000 tokens, 32 users, 3 minutes), which do pressure memory:

| Slots | TTFT p50 | Latency p50 | Latency p95 | Output tokens/s | Peak KV cache | Preemptions |
| --- | --- | --- | --- | --- | --- | --- |
| 16 | 25.9 s | 51.8 s | 54.8 s | 1,223 | 73.9% | 0 |
| 32 | 1.0 s | 32.0 s | 40.2 s | 1,738 | 99.4% | 90 |

All requests still succeeded during the preemptions, so error rate alone would not have shown them. A little over the memory limit was still a net win here. Where more slots start to hurt was not tested.

`--max-model-len` (short answers, 16 slots, 32 users): output was 1,312, 1,298 and 1,303 tokens/s at 2k, 4k and 8k. It's a per-request cap, not a throughput setting. The "maximum concurrency" vLLM logs (21.48x, 10.74x, 5.36x) is a worst case for full-length requests.

### Model comparison

Same 0.60 budget:

| | Qwen2.5-1.5B FP16 | Qwen2.5-3B AWQ 4-bit |
| --- | --- | --- |
| Weights | 2.98 GiB | 1.95 GiB |
| KV cache | 1.17 GiB, 43,984 tokens | 2.06 GiB, 59,968 tokens |
| Output tokens/s at 1 / 8 / 32 users | 96 / 678 / 1,298 | 110 / 804 / 1,358 |

The 3B answers were shorter (about 165 tokens against 199), so its latency is not directly comparable.

### Failover

With vLLM stopped, `chat` kept returning 200 from Ollama.

| Request | Time |
| --- | --- |
| vLLM up | 0.38-0.58 s |
| First request after vLLM stopped | 25-66 s |
| Second request | 7.6 s |
| During LiteLLM's 30 s cooldown | about 0.3 s |
| After the cooldown expires | 7.6-17.9 s |

Part of this is measured: with the container stopped, Docker's DNS takes about 3.6 s to fail the name `vllm`. The 25-66 s first request is **not fully explained**, and setting `num_retries` to 0 did not fix it.

### RAG

Backpressure, 32 clients for 60 s on `/ask`, measured before hybrid search was added:

| `MAX_IN_FLIGHT` | Answers/s | Accepted p50 | Accepted p95 | 429s | Peak vLLM queue |
| --- | --- | --- | --- | --- | --- |
| 8 | 3.5 | 1.99 s | 3.78 s | 1,392 | 0 |
| 16 (default) | 6.3 | 2.18 s | 4.80 s | 928 | 0 |
| 1000 (no real limit) | 7.3 | 3.78 s | 6.26 s | 0 | 16 |

Rejections returned in about 3 ms. Whether a limit protects better under much higher demand was not tested.

Retrieval, on 20 hand-written questions about one private 6-page PDF:

| Model | Search | Passage in top 4 | Passage in top 10 | MRR | Answers with expected word | Correct refusals |
| --- | --- | --- | --- | --- | --- | --- |
| 1.5B | Vector | 11/16 | 14/16 | 0.59 | 10/16 | 4/4 |
| 1.5B | Hybrid (default) | 13/16 | 16/16 | 0.71 | 11/16 | 3/4 |
| 3B AWQ | Vector | 11/16 | 14/16 | 0.59 | 9/16 | 4/4 |
| 3B AWQ | Hybrid | 13/16 | 16/16 | 0.71 | 10/16 | 4/4 |

This set is small, written after reading the document, and scored by keywords, so it compares options here and doesn't measure general accuracy. The 3B model guessed less but didn't answer more. Both failed the same hard questions, which suggests PDF extraction is the next thing to fix, as text from diagrams comes out fragmented. Questions are in `data/rag_eval.json`, which is not in git because it quotes that document.

Refusals are not reliable. With this README loaded as the document, "What is the capital of France?" got "Paris", though the same question was refused in the evaluation with the PDF loaded.

## Monitoring

The `LLM Serving` dashboard shows queue, KV cache, TTFT, latency, tokens per second, preemptions, VRAM and GPU utilization.

The one alert, `VLLMQueueBacklog`, fires when more than 8 requests wait for a full minute. It was tested under load. Queue length was chosen because at 32 users there were no errors, while TTFT rose from 46 ms to 2.4 s.

- Use Locust for numbers to quote. Grafana's latency comes from coarse histograms timed inside the Docker VM, and at 32 users it read p50 4.04 s and p95 9.28 s against Locust's 4.90 s and 5.02 s.
- GPU metrics use `nvidia-smi` because DCGM is poorly supported on WSL2. On a real Linux server, use NVIDIA's DCGM exporter.

## Scaling to 2× RTX 6000

Nothing in this section has been measured. Check the card first, because "RTX 6000" can mean the 48 GB RTX 6000 Ada or the older 24 GB Quadro RTX 6000. The figures below assume 48 GB each. Run `nvidia-smi` on the real server.

### Two ways to use two GPUs

| | One model per GPU behind LiteLLM | One model across both (tensor parallel) |
| --- | --- | --- |
| Use when | The model fits on one card | The model doesn't fit on one card |
| Setup | Two vLLM services, `device_ids: ["0"]` and `["1"]`, same `model_name` in LiteLLM | One vLLM with `--tensor-parallel-size 2` |
| Throughput | Close to double, requests go to either card | Less than double: GPUs synchronize at every step over PCIe |
| One GPU fails | The other keeps serving | That model goes down |

Default to one model per GPU. Tensor parallel only makes sense when a model is too big for one card. Check the interconnect too, because PCIe is much slower than NVLink.

```yaml
vllm-0:
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ["0"]
            capabilities: [gpu]
```

### VRAM math

```
VRAM needed = weights + KV cache + about 10-15% overhead
Weights:  FP16 ≈ 2 bytes per parameter (measured: 1.5B = 2.98 GiB)
          AWQ 4-bit ≈ 0.6-0.7 bytes per parameter (measured: 3B = 1.95 GiB)
```

| Model size | FP16 weights | AWQ 4-bit weights | On 48 GB cards |
| --- | --- | --- | --- |
| 7B | about 14 GB | about 5 GB | Fits one card, with lots of KV cache |
| 14B | about 28 GB | about 10 GB | Fits one card |
| 32B | about 64 GB | about 22 GB | FP16 needs both cards, AWQ fits one |
| 70B | about 140 GB | about 49 GB | FP16 doesn't fit. AWQ needs both cards |

Then measure it: read the KV cache size from vLLM's startup log, and load test with realistic prompt lengths, as these tests did.

### What else changes on a real server

- `--gpu-memory-utilization` can go near 0.90 with no display on the card.
- Put Docker's `data-root` and the model cache on a dedicated data disk.
- Pre-download weights, so startup never depends on Hugging Face.
- Add Alertmanager, because the alert here only shows in Prometheus and Grafana and notifies no one.
- Add a "vLLM is down" alert, and monitor LiteLLM itself.
- Use a secrets manager instead of `.env`, and TLS on the gateway.
- Load test from another machine, and repeat the runs. Most numbers here are from a single run.

## Project layout

```
docker-compose.yml   All services
litellm/config.yaml  Routes, timeouts, fallback
postgres/init.sql    Creates the litellm and rag databases
monitoring/          Prometheus, alert rule, Grafana dashboard
rag/                 FastAPI RAG app
loadtest/            Locust test, backpressure test, retrieval evaluation
results/             Raw results
```

To run the load tests:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r loadtest/requirements.txt
bash loadtest/run.sh vllm 32 my-label 2m
```
