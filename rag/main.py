"""RAG API. /ingest turns a PDF into searchable chunks in pgvector; /ask answers from them.

All model calls go through LiteLLM with this app's own key, using the "embed" and "chat" routes.
"""
import asyncio
import io
import os
import time
from contextlib import asynccontextmanager
from typing import Literal

import asyncpg
import httpx
from fastapi import FastAPI, HTTPException, UploadFile
from pgvector.asyncpg import register_vector
from pydantic import BaseModel, Field
from pypdf import PdfReader

DATABASE_URL = os.environ["DATABASE_URL"]
LITELLM_URL = os.environ["LITELLM_URL"]
LITELLM_KEY = os.environ["LITELLM_KEY"]
# Requests allowed inside /ask at once. Above this we answer 429 straight away.
MAX_IN_FLIGHT = int(os.environ.get("MAX_IN_FLIGHT", "16"))

CHUNK_CHARS = 800
CHUNK_OVERLAP = 150
EMBED_DIMENSIONS = 768
EMBED_BATCH = 16
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_ANSWER_TOKENS = 300

SYSTEM_PROMPT = (
    "You answer questions using only the context provided. "
    "If the context does not contain the answer, reply exactly: "
    "I don't know based on the documents."
)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS chunks (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    page INT NOT NULL,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR({EMBED_DIMENSIONS}) NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_source_idx ON chunks (source);
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS tsv TSVECTOR
    GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;
CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);
"""

VECTOR_SEARCH = """
SELECT source, page, chunk_index, content, 1 - (embedding <=> $1) AS score
FROM chunks ORDER BY embedding <=> $1 LIMIT $2
"""

# Reciprocal rank fusion: a chunk scores by its rank in each list, so vector and keyword
# scores never need comparing directly. Words are ORed, as ANDing every word rarely matches.
HYBRID_SEARCH = """
WITH query AS (
    SELECT replace(plainto_tsquery('english', $3)::text, ' & ', ' | ')::tsquery AS q
), by_vector AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> $1) AS rank
    FROM chunks ORDER BY embedding <=> $1 LIMIT $4
), by_keyword AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(tsv, query.q) DESC) AS rank
    FROM chunks, query WHERE tsv @@ query.q
    ORDER BY rank LIMIT $4
)
SELECT c.source, c.page, c.chunk_index, c.content,
       COALESCE(1.0 / (60 + v.rank), 0) + COALESCE(1.0 / (60 + k.rank), 0) AS score
FROM by_vector v FULL JOIN by_keyword k USING (id)
JOIN chunks c ON c.id = COALESCE(v.id, k.id)
ORDER BY score DESC LIMIT $2
"""
CANDIDATES_PER_LIST = 30

in_flight = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Separate read timeout: an answer can take a while, but a dead connection should fail fast.
    app.state.http = httpx.AsyncClient(
        base_url=LITELLM_URL,
        headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        timeout=httpx.Timeout(connect=5, read=120, write=10, pool=5),
        limits=httpx.Limits(max_connections=64),
    )
    async with asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4, init=register_vector) as pool:
        app.state.pool = pool
        yield
    await app.state.http.aclose()


async def ensure_schema():
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        await conn.execute(SCHEMA)
    finally:
        await conn.close()


asyncio.run(ensure_schema())
app = FastAPI(title="RAG API", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=10)
    mode: Literal["vector", "hybrid"] = "hybrid"


def chunk_text(text: str) -> list[str]:
    text = " ".join(text.split())
    step = CHUNK_CHARS - CHUNK_OVERLAP
    return [text[i : i + CHUNK_CHARS] for i in range(0, max(len(text) - CHUNK_OVERLAP, 1), step)]


def extract_chunks(data: bytes) -> list[tuple[int, str]]:
    """Returns (page number, chunk text) pairs."""
    chunks = []
    for number, page in enumerate(PdfReader(io.BytesIO(data)).pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            chunks.extend((number, chunk) for chunk in chunk_text(text))
    return chunks


async def call_litellm(path: str, body: dict) -> dict:
    try:
        response = await app.state.http.post(path, json=body)
    except httpx.TimeoutException:
        raise HTTPException(504, "Model backend timed out")
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach the model backend")
    if response.status_code == 429:
        raise HTTPException(503, "Gateway rate limit reached", headers={"Retry-After": "5"})
    if response.status_code != 200:
        raise HTTPException(502, f"Model backend returned {response.status_code}")
    return response.json()


async def embed(texts: list[str]) -> list[list[float]]:
    result = await call_litellm("/v1/embeddings", {"model": "embed", "input": texts})
    return [item["embedding"] for item in sorted(result["data"], key=lambda item: item["index"])]


@app.get("/health")
async def health():
    await app.state.pool.fetchval("SELECT 1")
    return {"status": "ok", "in_flight": in_flight, "max_in_flight": MAX_IN_FLIGHT}


@app.post("/ingest")
async def ingest(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 25 MB")
    source = file.filename or "upload.pdf"
    # PDF parsing is CPU work: run it off the event loop so /ask keeps responding.
    try:
        chunks = await asyncio.to_thread(extract_chunks, data)
    except Exception:
        raise HTTPException(400, "Could not read this file as a PDF")
    if not chunks:
        raise HTTPException(422, "No extractable text. A scanned PDF would need OCR first.")

    start = time.perf_counter()
    embeddings = []
    for i in range(0, len(chunks), EMBED_BATCH):
        # nomic-embed-text expects these task prefixes on documents and queries.
        batch = [f"search_document: {text}" for _, text in chunks[i : i + EMBED_BATCH]]
        embeddings.extend(await embed(batch))

    # One transaction, so re-ingesting replaces a document without a half-empty moment.
    async with app.state.pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM chunks WHERE source = $1", source)
        await conn.executemany(
            "INSERT INTO chunks (source, page, chunk_index, content, embedding) VALUES ($1, $2, $3, $4, $5)",
            [(source, page, i, text, vec) for i, ((page, text), vec) in enumerate(zip(chunks, embeddings))],
        )
    return {"source": source, "chunks": len(chunks), "embed_seconds": round(time.perf_counter() - start, 2)}


@app.post("/ask")
async def ask(request: AskRequest):
    global in_flight
    # Backpressure: refuse immediately rather than let an unbounded queue build behind us.
    if in_flight >= MAX_IN_FLIGHT:
        raise HTTPException(429, "Too many requests in progress", headers={"Retry-After": "1"})
    in_flight += 1
    try:
        return await answer(request)
    finally:
        in_flight -= 1


async def retrieve(request: AskRequest, query_vector: list[float]) -> list:
    if request.mode == "vector":
        return await app.state.pool.fetch(VECTOR_SEARCH, query_vector, request.top_k)
    return await app.state.pool.fetch(
        HYBRID_SEARCH, query_vector, request.top_k, request.question, CANDIDATES_PER_LIST
    )


@app.post("/search")
async def search(request: AskRequest):
    """Retrieval only, with no model answer. Used to evaluate search quality."""
    query_vector = (await embed([f"search_query: {request.question}"]))[0]
    rows = await retrieve(request, query_vector)
    return [{"page": row["page"], "chunk": row["chunk_index"], "text": row["content"]} for row in rows]


async def answer(request: AskRequest) -> dict:
    start = time.perf_counter()
    query_vector = (await embed([f"search_query: {request.question}"]))[0]
    embedded_at = time.perf_counter()

    rows = await retrieve(request, query_vector)
    searched_at = time.perf_counter()
    if not rows:
        raise HTTPException(409, "No documents ingested yet")

    context = "\n\n".join(f"[Source {i}]\n{row['content']}" for i, row in enumerate(rows, start=1))
    result = await call_litellm(
        "/v1/chat/completions",
        {
            "model": "chat",
            "temperature": 0,
            "max_tokens": MAX_ANSWER_TOKENS,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {request.question}"},
            ],
        },
    )
    done_at = time.perf_counter()
    return {
        "answer": result["choices"][0]["message"]["content"],
        "answered_by": result.get("model"),
        "sources": [
            {
                "source": row["source"],
                "page": row["page"],
                "chunk": row["chunk_index"],
                "score": round(float(row["score"]), 3),
                "text": row["content"],
            }
            for row in rows
        ],
        "timing_ms": {
            "embed": round((embedded_at - start) * 1000),
            "search": round((searched_at - embedded_at) * 1000),
            "generate": round((done_at - searched_at) * 1000),
        },
    }
