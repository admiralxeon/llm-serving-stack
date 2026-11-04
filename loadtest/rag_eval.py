"""Compares retrieval modes on a hand-written question set (data/rag_eval.json, not in git,
because it quotes the private test document). Only aggregate scores are saved.

Retrieval hit = a top-k chunk contains an expected phrase. Answer hit = the answer contains an
expected word. These are rough keyword checks, not a judgement of whether an answer is good.
Usage: .venv/Scripts/python loadtest/rag_eval.py <label>
"""
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
EVAL = json.loads((ROOT / "data" / "rag_eval.json").read_text(encoding="utf-8"))
RESULTS_FILE = ROOT / "results" / "RAG_RETRIEVAL.md"
URL = "http://localhost:8080"
REFUSAL = "don't know"
label = sys.argv[1]


def post(path, **body):
    response = requests.post(f"{URL}{path}", json=body, timeout=300)
    response.raise_for_status()
    return response.json()


def first_hit_rank(chunks, phrases):
    for rank, chunk in enumerate(chunks, start=1):
        if any(p in chunk["text"].lower() for p in phrases):
            return rank
    return None


for mode in ("vector", "hybrid"):
    ranks = []
    answer_hits = refusals = fallbacks = 0
    missed = []
    for item in EVAL["answerable"]:
        rank = first_hit_rank(post("/search", question=item["q"], top_k=10, mode=mode), item["chunk_has"])
        ranks.append(rank)
        reply = post("/ask", question=item["q"], top_k=4, mode=mode)
        fallbacks += reply["answered_by"] != "chat"
        answer = reply["answer"].lower()
        hit = any(word in answer for word in item["answer_has"])
        answer_hits += hit
        if not hit or not rank or rank > 4:
            missed.append(f"{item['q']} (rank {rank}, answer {'ok' if hit else 'miss'})")
    for question in EVAL["unanswerable"]:
        reply = post("/ask", question=question, top_k=4, mode=mode)
        fallbacks += reply["answered_by"] != "chat"
        refusals += REFUSAL in reply["answer"].lower()

    total = len(ranks)
    at_4 = sum(1 for r in ranks if r and r <= 4)
    at_10 = sum(1 for r in ranks if r)
    mrr = sum(1 / r for r in ranks if r) / total
    print(f"\n{mode}: recall@4 {at_4}/{total}, recall@10 {at_10}/{total}, MRR {mrr:.2f}, "
          f"answers {answer_hits}/{total}, refusals {refusals}/{len(EVAL['unanswerable'])}, "
          f"answered by fallback model: {fallbacks}")
    for line in missed:
        print("  -", line)

    if not RESULTS_FILE.exists():
        RESULTS_FILE.write_text(
            "# RAG retrieval evaluation\n\n"
            "Hand-written questions on one private 6-page PDF. Keyword checks. "chunks-800" and "1.5B" are the Qwen2.5-1.5B model.\n\n"
            "| Run | Mode | Recall@4 | Recall@10 | MRR | Answers with expected word | Correct refusals |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
        )
    with RESULTS_FILE.open("a") as f:
        f.write(f"| {label} | {mode} | {at_4}/{total} | {at_10}/{total} | {mrr:.2f} "
                f"| {answer_hits}/{total} | {refusals}/{len(EVAL['unanswerable'])} |\n")
