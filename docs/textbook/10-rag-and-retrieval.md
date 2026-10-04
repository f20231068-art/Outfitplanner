# Chapter 10. Retrieval, Embeddings and Memory (RAG)

> **Learning objectives.** Explain why and when to retrieve; build a retrieval-augmented generation (RAG) pipeline end to end (ingest, chunk, embed, index, retrieve, rerank, generate, verify); compare dense, sparse and hybrid retrieval; use vector stores including pgvector; evaluate retrieval and generation separately; design agent memory and "context engineering"; and see how this project's search tool is retrieval without vectors and where RAG would plug in.
>
> **Prerequisites.** Chapters 5-7.

**RAG** (retrieval-augmented generation) is the single most common architecture in business AI applications: *find the relevant information, put it in the prompt, and have the model answer from it.* Almost every FDE engagement ("a chatbot over our documents", "an assistant for our support team") is some variant. This chapter is therefore important even though AI Stylist does not use a vector database.

---

## 10.1 Why retrieval?

A model's built-in knowledge is **frozen** (training cutoff), **generic** (not your company's documents), **uncheckable** (no citations), and **fallible** (hallucination). Retrieval addresses each: fetch *current, private, citable* information at question time and let the model reason over it.

Three ways to give a model knowledge, and when to use each:

| Approach | What | Strengths | Weaknesses |
|---|---|---|---|
| **Prompting with a small fixed context** | paste the policy into the system prompt | simplest; cache-friendly | does not scale past the context window; cost per call |
| **Long-context stuffing** | put whole documents into a very long context | no pipeline to build | cost and latency scale with tokens; accuracy degrades for buried facts; no per-user access control |
| **RAG** | retrieve the few relevant passages per question | scalable, updatable, citable, permission-aware | retrieval quality is now the bottleneck; a pipeline to run |
| **Fine-tuning** | train the model on your data | style, format, niche behaviours, latency | poor at injecting facts, hard to update, no citations, costs |

Rules of thumb: **facts and documents → retrieval; style and behaviour → prompting or fine-tuning; small stable knowledge → in the prompt.** Combine them: fine-tune for tone, retrieve for facts.

### Retrieval does not have to use vectors

**This project is a retrieval system.** The "documents" are Google Shopping results; the "query" is built from a spec (`men olive green oversized cotton t-shirt`); the "retriever" is SerpAPI; the "reranker" is the deterministic **verifier**; the "generation" step is the user-facing outfit summary written by code. The agent *never asks a model to remember products*: it **retrieves, verifies and presents**. That is the RAG philosophy in its strictest form: **ground answers in retrieved facts, then check them.**

## 10.2 Embeddings

An **embedding model** maps text (or images, audio) to a vector so that *semantically similar inputs are close* under cosine similarity or dot product (Chapter 5). They are separate, cheaper models than chat models.

Practical facts:

* **Dimensions** typically 384 to 3072. More dimensions can capture more nuance but cost more storage and search time. Some models support **truncation (Matryoshka representations)**: use the first 256 of 1024 dimensions with a graceful quality drop.
* **Normalisation**: use unit-length vectors so dot product equals cosine.
* **Asymmetric search**: queries are short and documents long; some models use **different prefixes or modes** for "query" and "document" text. Follow the model card.
* **Multilingual** models matter in India (Hindi, Tamil, code-mixed "Hinglish"); test on *your* language mix.
* **Domain fit**: general models can miss jargon; test and, if needed, pick a domain model or fine-tune embeddings.
* **Never mix models** in one index; **version** the embedding model and re-embed everything when it changes (store `embedding_model` with each row).
* **Cost**: embedding a corpus is a one-time (plus incremental) cost; embedding each query is a small per-request cost. Cache query embeddings for repeated queries.
* **Uses beyond search**: deduplication, clustering, classification with a tiny classifier on top, recommendations, anomaly detection, semantic caching.

## 10.3 The RAG pipeline

Two phases:

**Ingestion (offline / incremental):** `load → parse/clean → chunk → (enrich with metadata) → embed → index`

**Query (online):** `understand/rewrite query → retrieve → (filter) → rerank → assemble context → generate with citations → verify → respond`

### Loading and parsing

Real documents are messy: PDFs with columns and tables, scanned images (need OCR), HTML with navigation junk, spreadsheets, slide decks, Confluence/Notion/Drive exports. **Parsing quality caps everything downstream.** Garbage in, garbage retrieved. Invest in extraction: preserve headings, table structure, page numbers and source URLs; strip boilerplate; handle duplicates and versions. Always keep a **stable document id, source, version, timestamp and access-control list** with every chunk.

### Chunking

You cannot embed a 200-page document as one vector (it blurs everything), nor retrieve it as one chunk (it overflows the prompt). Split it into **chunks**:

| Strategy | Idea | Notes |
|---|---|---|
| Fixed size with overlap | N tokens, overlap M (a sliding window, Chapter 4) | simple baseline; 200-500 tokens, 10-20% overlap are common starting points |
| Recursive character/structure splitting | split on paragraphs, then sentences, then words | respects natural boundaries |
| Structure-aware | split by headings/sections/slides/table rows/code functions | best for structured docs; carry the heading path as context |
| Semantic | split where embedding similarity between sentences drops | better coherence, more compute |
| Parent-child ("small to big") | retrieve small chunks for precision, but pass the larger parent section to the model | good precision *and* context |
| Contextual chunks | prepend a short generated summary of where the chunk sits in the document | helps chunks that are ambiguous alone |

Trade-off: **small chunks** = precise retrieval, but fragmented context; **large chunks** = coherent context, but diluted embeddings and wasted prompt tokens. There is no universal best; **measure retrieval quality on your own questions** while varying chunk size and overlap.

```python
def chunk_words(words, size=200, overlap=40):
    step = size - overlap
    for i in range(0, len(words), step):
        yield words[i:i + size]
        if i + size >= len(words): break
```

### Metadata

Store with each chunk: `doc_id, title, section, page, url, author, date, version, language, tenant/user permissions, chunk_index`. Metadata enables **filtering** (only this customer's documents; only the latest version; only after a date), **citations**, **freshness handling**, and **access control**.

## 10.4 Retrieval methods

### Dense retrieval (vector search)

Embed the query; find nearest chunk vectors. Great at **meaning** ("how do I return a jacket?" finds "refund policy for apparel"), weak at **exact tokens** (product codes, error messages, names, numbers, rare terms).

### Sparse retrieval (lexical): BM25

The classical search-engine approach. An **inverted index** maps each term to the documents containing it. **TF-IDF** weights terms by frequency in the document times rarity across the corpus; **BM25** improves it with term-frequency saturation and length normalisation:

`score(D, Q) = Σ_q IDF(q) · f(q,D)·(k1 + 1) / ( f(q,D) + k1·(1 - b + b·|D|/avgdl) )`, with `IDF(q) = ln( (N - n_q + 0.5)/(n_q + 0.5) + 1 )`

(`k1` ≈ 1.2-2, `b` ≈ 0.75; N documents; n_q documents containing q; f term frequency; |D| document length.) Strong on **exact matches** and needs no model. A compact implementation:

```python
import math
from collections import Counter

def bm25_scores(query_terms, docs_tokens, k1=1.5, b=0.75):
    N = len(docs_tokens)
    avgdl = sum(len(d) for d in docs_tokens) / N
    df = Counter(t for d in docs_tokens for t in set(d))                  # document frequency
    scores = []
    for d in docs_tokens:
        tf, dl, s = Counter(d), len(d), 0.0
        for q in query_terms:
            if q in tf:
                idf = math.log((N - df[q] + 0.5) / (df[q] + 0.5) + 1)
                s += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * dl / avgdl))
        scores.append(s)
    return scores
```

Note the family resemblance to this repo's verifier: tokenise, normalise, count matches. The difference is purpose: the verifier makes a *yes/no decision with evidence*, BM25 produces a *ranking score*.

### Hybrid retrieval

Run **both** dense and sparse retrieval and **fuse** the ranked lists. The standard, parameter-light fusion is **Reciprocal Rank Fusion (RRF)**:

```python
def rrf(rank_lists, k=60):
    score = {}
    for ranks in rank_lists:                          # each: a list of doc ids, best first
        for r, doc in enumerate(ranks, start=1):
            score[doc] = score.get(doc, 0.0) + 1.0 / (k + r)
    return sorted(score, key=score.get, reverse=True)
```

Hybrid is the sensible default for production search: it catches both paraphrases and exact identifiers.

### Reranking

First-stage retrieval is fast but coarse (top 50-100). A **reranker** (a **cross-encoder** model that reads the query and a candidate *together* and outputs a relevance score, or an LLM used as a judge) re-orders the shortlist to the best 3-10. Cost is higher per pair, so apply it only to the shortlist. This **retrieve-then-rerank** pattern is the biggest cheap quality win in most RAG systems. *The verifier in this repo is a deterministic reranker plus filter: it ranks candidates by `(confidence, score, price)` and rejects non-matches.*

### Query-side improvements

* **Query rewriting**: turn a chat turn ("what about in blue?") into a standalone query ("men's blue chinos under 2500") using the history. (This is what `gather_prefs` and the planner effectively do for search.)
* **Multi-query**: generate several paraphrases and merge results.
* **HyDE**: have the model draft a hypothetical answer, embed *that* for retrieval.
* **Decomposition**: split multi-part questions into sub-queries.
* **Metadata filters**: translate "last year's policy" into a date filter.
* **MMR (maximal marginal relevance)**: choose results that are relevant *and* diverse, avoiding five near-duplicates.

### Choosing k

`k` (how many chunks to pass) trades **recall** (include the needed fact) against **noise and cost**. Typical final k: 3-8 chunks. Measure recall@k at several values; add a **relevance threshold** so that irrelevant results are *not* passed to the model, and so "no good result" can be detected honestly.

## 10.5 Vector stores and ANN indexes

Brute-force similarity (Chapter 4) is O(N·d). At scale you use an **approximate nearest-neighbour (ANN)** index (Chapter 5): **HNSW** (graph; fast, high recall, more memory; the common default), **IVF** (clustering; compact), **PQ** (compression). Trade-off knobs: build effort (`m`, `ef_construction`), search effort (`ef_search`/`nprobe`): higher means better recall and slower queries.

| Option | Notes |
|---|---|
| **pgvector** (Postgres extension) | vectors in the same database as your application data; SQL joins and filters; transactions; backups you already have. Excellent default when you already run Postgres and have up to millions of vectors |
| **Dedicated vector DBs** (Pinecone, Qdrant, Weaviate, Milvus) | scale-out, advanced filtering, managed options; another system to operate and keep in sync |
| **Search engines** (Elasticsearch/OpenSearch) | mature hybrid (BM25 + vectors), faceting, analyzers |
| **Libraries** (FAISS, hnswlib) | in-process indexes; great for prototypes and offline jobs; you handle persistence |
| **Lightweight stores** (Chroma, SQLite-vec, LanceDB) | embedded/dev-friendly |

**pgvector sketch** (fits naturally next to this repo's Postgres and plain-SQL migrations):

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE knowledge_chunks (
    id             bigserial PRIMARY KEY,
    doc_id         text        NOT NULL,
    chunk_index    integer     NOT NULL,
    content        text        NOT NULL,
    embedding      vector(1536) NOT NULL,           -- must match the model's dimension
    embedding_model text       NOT NULL,            -- re-embed when this changes
    tenant_id      uuid,                            -- for access control filters
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (doc_id, chunk_index)
);
CREATE INDEX knowledge_chunks_hnsw ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- top 5 by cosine distance, filtered by tenant (the filter is a SECURITY control, not an optimisation)
SELECT id, doc_id, content, 1 - (embedding <=> $1) AS similarity
FROM knowledge_chunks
WHERE tenant_id = $2
ORDER BY embedding <=> $1
LIMIT 5;
```

(`<=>` is cosine distance, `<->` Euclidean, `<#>` negative inner product. Build the ANN index *after* bulk-loading data when possible. Combine with Postgres full-text search (`tsvector`) for hybrid retrieval in one database.)

**Operational concerns:** incremental updates and deletes (a deleted document must disappear from search *and* from caches), re-indexing on embedding-model changes, index memory, backup, per-tenant isolation, and monitoring recall.

## 10.6 Generation with retrieved context

### The prompt

```
You answer questions using ONLY the context below. If the context does not contain the answer, say
"I could not find that in the provided documents." Cite sources as [doc_id#chunk].

<context>
[policy-12#3] Returns are accepted within 14 days if the tag is attached...
[policy-12#4] Refunds are issued to the original payment method within 5 business days...
</context>

Question: How long do I have to return a jacket?
```

Practices:

* **Delimit** the retrieved text clearly and tell the model it is *data*, not instructions (prompt-injection defence, Chapter 21: a retrieved document can contain "ignore previous instructions").
* **Require citations** (ids you can map back to sources and show to users).
* **Define the "I don't know" behaviour** and test that it triggers.
* **Order and size**: put the most relevant chunks first and last (the middle is read less reliably) and keep within a **token budget**.
* **Answer in the user's language**; keep identifiers verbatim.
* **Verify**: check that quoted numbers, names and links appear in the retrieved context (a deterministic "groundedness" check, as the stylist verifier checks that a colour or price appears in product data).

### Failure analysis: which half broke?

When a RAG answer is wrong, always ask first: **was the right chunk retrieved?**

| Symptom | Likely cause | Fix |
|---|---|---|
| Right answer not in retrieved chunks | retrieval/indexing: bad chunking, embedding mismatch, missing documents, no hybrid, too small k | improve chunking, add hybrid and rerank, query rewriting, check ingestion |
| Right chunk retrieved, wrong answer | generation: model ignored or misread context, too much noise, prompt unclear | reorder, fewer chunks, stronger instructions, better model, verify citations |
| Confident answer with no support | model used parametric memory | stricter "only from context" prompting, refusal tests, groundedness checks |
| Stale or contradictory answers | multiple versions indexed | versioning and filters, delete old chunks, use dates |
| Slow | big context, many calls | smaller k, caching, smaller model for rewrite, parallel retrieval |

## 10.7 Evaluating RAG

Evaluate **retrieval** and **generation** separately (Chapter 12 has the general method).

**Build a test set**: 50-200 realistic questions with the expected supporting document(s) (and ideally a reference answer). Source them from real user questions, support tickets, and SME-written questions; supplement with synthetic questions generated *from* chunks (then manually check a sample).

**Retrieval metrics** (need relevance labels):
* **Hit rate / recall@k**: did the relevant chunk appear in the top k?
* **MRR (mean reciprocal rank)**: average of `1/rank` of the first relevant result.
* **nDCG@k**: rewards putting highly relevant results near the top (graded relevance).
* **Precision@k / context precision**: how much of what you retrieved is useful.

**Generation metrics** (often judged by an LLM calibrated on human labels):
* **Faithfulness / groundedness**: is every claim supported by the retrieved context?
* **Answer relevance / correctness**: does it answer the question, and match the reference?
* **Citation accuracy**: do the cited sources actually support the claim?
* **Refusal correctness**: when the answer is not in the corpus, does it say so?

Tools and frameworks exist (RAGAS, TruLens, DeepEval, Langfuse/Braintrust evals, promptfoo), but the dataset and the discipline matter more than the library. Track metrics **per release** so a chunking change that improves recall@5 by 8 points but hurts faithfulness shows up.

## 10.8 Advanced patterns

* **Agentic RAG**: the model decides whether and what to search, can search several times, and reads results iteratively (a tool-calling agent with a `search_docs` tool). Better for complex questions; costlier and less predictable. Start with a single retrieval step.
* **GraphRAG / knowledge graphs**: extract entities and relations, retrieve connected facts; helps multi-hop questions ("which suppliers of X also supply Y?").
* **Late-interaction retrieval** (ColBERT-style): store per-token vectors, higher accuracy, larger indexes.
* **Structured data**: for databases and spreadsheets, **text-to-SQL** with a **read-only role, allow-listed tables, query timeouts, row limits and validation**, never raw model SQL with write access (SQL injection by model).
* **Multimodal RAG**: embed images, slides and charts; use vision models to caption or read them.
* **Caching**: exact-match caches for repeated questions; **semantic caches** (return a stored answer for a very similar question: fast and cheap, but risks wrong reuse: use high thresholds and only for safe content).
* **Freshness**: incremental ingestion pipelines, change-data-capture, TTLs, "as of" dates in answers.
* **Access control**: filter by the **requesting user's permissions at retrieval time** (document-level ACLs in metadata). A RAG system that retrieves a document the user cannot access is a **data breach by design**. Never rely on the model to hide restricted content.
* **PII and compliance**: classify and redact sensitive data before indexing; honour deletion requests (India's Digital Personal Data Protection Act 2023, GDPR) by deleting source, chunks, embeddings and caches.

## 10.9 Memory for agents

"Memory" in agents is just **what gets put in the context, from where**:

| Kind | What | Where it lives | In this project |
|---|---|---|---|
| **Working / short-term** | the current conversation and scratch state | the thread's state (checkpoint) | `messages`, `prefs`, `outfits` in LangGraph state, persisted in Postgres |
| **Summary memory** | a running summary replacing old turns | state | not used (conversations are short) |
| **Long-term semantic** | facts and preferences about a user across sessions | a store, retrieved by similarity or key | not built (`prefs` carry over within a thread only) |
| **Episodic** | records of past tasks and outcomes ("last time this style was chosen, the user liked X") | a store | not built; the saved `outfits` table is the raw material |
| **Procedural** | learned instructions/skills | prompts, skills, files | prompts in `prompts/stylist` |

Design principles: **store structured facts** (budget, sizes, dislikes) rather than raw transcripts; **retrieve only what is relevant** per turn; give users **visibility and deletion** of what is remembered; avoid storing sensitive data without a reason; and defend against **memory poisoning** (an attacker getting a malicious "fact" saved that later steers the agent). LangGraph offers a **store** abstraction for cross-thread long-term memory; the `thread_id`-scoped checkpoint is short-term.

## 10.10 Context engineering

The skill that replaced "prompt tricks": **deliberately deciding what the model sees at each step.** The context holds the system prompt, tool definitions, retrieved documents, history, tool results and the user message, and it has a **budget** (tokens, cost, latency, attention).

Practical rules:

1. **Give the minimum sufficient context.** Irrelevant text hurts accuracy and costs money.
2. **Structure it**: labelled sections, consistent delimiters, important facts near the top or end.
3. **Trim and summarise history**; clear stale tool results; keep invariants (constraints) pinned.
4. **Return compact tool results** (the `SearchProductsResult` returns trimmed products and warnings, not raw pages).
5. **Use prompt caching** by keeping the stable prefix stable (Chapter 14).
6. **Separate stages with their own contexts** (the stylist's three prompts each get only what they need: extraction sees the chat; planning sees a JSON summary of prefs, style and notes, *not* the whole chat, which keeps it cheap and focused).
7. **Keep state outside the context** and inject what is needed (the database is your long-term memory).

## 10.11 How RAG could plug into AI Stylist (a design exercise)

Ideas that would add *retrieval over text* to a product that today retrieves *products*:

* **A fashion knowledge base** (style guides, colour-pairing rules, fabric care, fit guides, occasion dress codes) embedded into `knowledge_chunks`; the planner retrieves relevant snippets by style and occasion and cites them in rationales. Evaluate: does retrieval improve garment variety and colour coherence (a taste judge)?
* **Size and fit help**: retrieve size charts and brand fit notes for the chosen items.
* **Store policies** (returns, delivery) answered on the Buy flow.
* **Review mining**: embed product reviews to filter "runs small" items for tall shoppers.
* **Semantic product search**: embed product titles and the spec text to find candidates when keyword search misses (but keep the verifier: *embedding similarity is not verification*).

Constraints you would have to design: licensing of content, access control (none needed for public guides), freshness (no), PII (none), evaluation (new rubric), cost (embedding + storage trivial), and the **verifier-first principle**: retrieved *advice* may shape the plan, but **products still pass deterministic verification**.

## 10.12 A minimal RAG in plain Python (provider-neutral)

```python
import math

def embed(texts: list[str]) -> list[list[float]]:
    """Call your embedding provider here; return unit vectors."""
    raise NotImplementedError

def cosine(a, b): return sum(x * y for x, y in zip(a, b))        # unit vectors: dot == cosine

class Index:
    def __init__(self): self.items = []                          # (id, text, vector)
    def add(self, chunks: list[tuple[str, str]]):
        vectors = embed([t for _, t in chunks])
        self.items += [(i, t, v) for (i, t), v in zip(chunks, vectors)]
    def search(self, query: str, k: int = 4, min_sim: float = 0.3):
        q = embed([query])[0]
        scored = sorted(((cosine(q, v), i, t) for i, t, v in self.items), reverse=True)[:k]
        return [(s, i, t) for s, i, t in scored if s >= min_sim]   # a threshold enables "no result"

def answer(index: Index, question: str, llm) -> str:
    hits = index.search(question)
    if not hits:
        return "I could not find that in the provided documents."
    context = "\n".join(f"[{i}] {t}" for _, i, t in hits)
    prompt = ("Answer ONLY from the context. Cite ids like [id]. If unsure, say you cannot find it.\n"
              f"<context>\n{context}\n</context>\nQuestion: {question}")
    return llm(prompt)
```

Notice three production habits already present: a **similarity threshold**, an explicit **no-answer path**, and **ids for citation**.

## Common mistakes

* Chunking by arbitrary size without looking at the documents.
* Dense-only retrieval for identifiers, codes and names.
* No reranking; passing 20 noisy chunks.
* Ignoring access control at retrieval time.
* Mixing embeddings from different models, or not recording which model produced them.
* Evaluating only the final answer, so you cannot tell retrieval failures from generation failures.
* Letting retrieved text act as instructions (prompt injection).
* Believing a similarity score is a probability of correctness.
* Never re-indexing deleted or updated documents.

## Summary

* Retrieval grounds a model in current, private, citable data; use RAG for facts, prompting/fine-tuning for behaviour.
* Pipeline: parse → chunk → embed → index; query → rewrite → hybrid retrieve → rerank → assemble → generate with citations → verify.
* Dense catches meaning; BM25 catches exact terms; hybrid with RRF plus a reranker is a strong default.
* pgvector is a pragmatic default if you already have Postgres; filters double as access control.
* Evaluate retrieval and generation separately; always diagnose which half failed.
* Memory = deciding what enters the context; context engineering is the discipline.
* AI Stylist is retrieval + verification without vectors; RAG could add knowledge snippets, never replace the verifier.

## Key terms

*RAG, embedding, chunking, overlap, metadata filter, dense retrieval, BM25, inverted index, hybrid search, RRF, reranker, cross-encoder, ANN, HNSW, pgvector, recall@k, MRR, nDCG, faithfulness, groundedness, HyDE, MMR, agentic RAG, GraphRAG, semantic cache, context engineering, long-term memory.*

## Interview questions

1. Design a RAG system over 10,000 internal PDFs. Walk through ingestion and query paths.
2. Dense vs sparse retrieval: when does each fail? How do you combine them?
3. How do you choose chunk size? How do you evaluate your choice?
4. Why add a reranker? Where does it sit?
5. How do you enforce per-user document permissions in RAG?
6. A user complains an answer is wrong. How do you debug retrieval vs generation?
7. What are the risks of semantic caching?
8. When is long-context stuffing better than RAG? When worse?
9. How would you add memory to a chatbot without leaking users' data?

## Exercises

1. Build the minimal RAG above over 30 Markdown files (use any embedding API or a local model). Create 20 questions with expected sources and compute recall@1/3/5.
2. Add BM25 and RRF; measure the change on questions containing exact identifiers.
3. Add a pgvector table to the local Postgres (a new migration `002_knowledge.sql`) and write a `search_knowledge(query, k)` function with a tenant filter and a test that proves tenant A cannot retrieve tenant B's chunks.
4. Write a "groundedness check" that verifies every number in an answer appears in the retrieved context, and return `unverified` otherwise.
5. Sketch how `plan_outfits` would use retrieved style snippets without letting them bypass `verify_product`.
