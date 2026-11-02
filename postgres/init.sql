-- Runs once, on the first start of an empty data volume.
-- One Postgres instance, two databases: LiteLLM's bookkeeping and the RAG vectors.
CREATE DATABASE litellm;
CREATE DATABASE rag;

\connect rag
CREATE EXTENSION IF NOT EXISTS vector;
