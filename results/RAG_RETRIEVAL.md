# RAG retrieval evaluation

Hand-written questions on one private 6-page PDF. Keyword checks. "chunks-800" and "1.5B" are the Qwen2.5-1.5B model.

| Run | Mode | Recall@4 | Recall@10 | MRR | Answers with expected word | Correct refusals |
| --- | --- | --- | --- | --- | --- | --- |
| chunks-800 | vector | 11/16 | 14/16 | 0.59 | 10/16 | 4/4 |
| chunks-800 | hybrid | 13/16 | 16/16 | 0.71 | 11/16 | 3/4 |
| 3B-AWQ run1 | vector | 11/16 | 14/16 | 0.59 | 9/16 | 4/4 |
| 3B-AWQ run1 | hybrid | 13/16 | 16/16 | 0.71 | 10/16 | 4/4 |
| 3B-AWQ run2 | vector | 11/16 | 14/16 | 0.59 | 9/16 | 4/4 |
| 3B-AWQ run2 | hybrid | 13/16 | 16/16 | 0.71 | 10/16 | 4/4 |
| 1.5B run2 | vector | 11/16 | 14/16 | 0.59 | 10/16 | 4/4 |
| 1.5B run2 | hybrid | 13/16 | 16/16 | 0.71 | 11/16 | 3/4 |
