# Agentic RAG with Claude and Voyage

A walkthrough of `claude_implementation/` — what Anthropic actually recommends for
retrieval-augmented generation, how this code implements it, and where it diverges
from `pro_implementation/`.

---

## 0. TL;DR

Three ideas carry most of the weight:

1. **A chunk that can't be understood alone can't be retrieved alone.** Before indexing,
   Claude reads the *whole* document and writes a sentence or two situating each chunk in
   it. That text is prepended to the chunk. Anthropic measured a **35% drop in retrieval
   failures** from this alone.
2. **Two retrievers beat one.** A dense (embedding) search and a lexical (BM25) search fail
   on different queries. Running both and fusing the rankings takes the failure reduction
   to **49%**; adding a reranker takes it to **67%**.
3. **Let Claude drive.** Instead of a fixed `retrieve → answer` pipeline, Claude gets a
   search tool and decides what to look up, reads the results, and searches again when the
   question needs it.

```
                        ┌─ Voyage dense search ─┐
question ── Claude ──► ─┤                        ├─► RRF fusion ─► rerank-2.5 ─► 20 chunks ─► Claude
   ▲       (decides)    └─ BM25 lexical search ─┘                                                │
   └──────────────────────── searches again if needed ◄───────────────────────────────────────────┘
```

---

## Part 1 — Anthropic's guidelines for agentic RAG

### 1.1 First question: should this be an agent at all?

Anthropic's guidance is emphatic about **starting simple**. Their tiers:

| Tier | Use for | Surface |
|---|---|---|
| Single call | Classification, summarization, extraction, straight Q&A | One `messages.create` |
| Workflow | Multi-step pipelines where *you* control the logic | API + tool use, your loop |
| Agent | Open-ended tasks where the model controls the logic | API + tool use, model-driven loop |

Before reaching for the agent tier, check all four:

- **Complexity** — is the task multi-step and hard to fully specify in advance?
- **Value** — does the outcome justify higher cost and latency?
- **Viability** — is Claude actually good at this task type?
- **Cost of error** — can mistakes be caught and recovered from?

"No" to any one of them means stay at a simpler tier.

**Does RAG over a company knowledge base qualify?** Honestly, it's marginal. A single
well-retrieved context window answers most questions about Insurellm. The agent tier earns
its place on the subset of questions that need more than one lookup — *"who studied at
Manchester University and what do they work on now?"* requires finding the person, then
looking up their work. A fixed pipeline retrieves once for the whole question and blurs
both halves into one query. That's the case this design is built for; for one-hop factual
questions the agent is strictly more expensive than the pipeline it replaces.

> **Takeaway:** "agentic" isn't automatically better. It's better when the *number and
> shape of retrievals cannot be known in advance*.

### 1.2 The problem Contextual Retrieval solves

Standard RAG splits documents into chunks and embeds each one independently. That
independence is the bug. Consider a chunk from a contract:

> The renewal premium rose 8% in the second year, with a cap of 12% thereafter.

Embed that on its own and ask *"what were the Apex Reinsurance renewal terms?"* — the chunk
never surfaces. It doesn't contain the words "Apex", "Reinsurance", or "terms". The
document knew, but the chunk doesn't, and the chunk is what got indexed.

### 1.3 The technique

Before indexing, ask the model to situate each chunk within its source document, then
prepend that explanation to the chunk. Anthropic's instruction is:

> "Please give a short succinct context to situate this chunk within the overall document
> for the purposes of improving search retrieval."

50–100 tokens. The chunk above becomes:

> *This chunk is from the Apex Reinsurance contract between Insurellm and Apex, describing
> the renewal pricing schedule.*
>
> The renewal premium rose 8% in the second year, with a cap of 12% thereafter.

Now it retrieves. Critically, **the model must see the entire document** while writing
that context — that whole-document visibility is the mechanism. A per-chunk summary
generated from the chunk alone adds nothing it didn't already have.

Anthropic's measured results, against a plain-embedding baseline:

| Pipeline | Retrieval failure rate |
|---|---|
| Baseline embeddings | — |
| Contextual embeddings | **−35%** |
| + contextual BM25 | **−49%** |
| + reranking | **−67%** |

### 1.4 Why a lexical index alongside the vectors

Embeddings capture *meaning* and are excellent at paraphrase — "who runs the company"
finds "Avery Lancaster serves as CEO". They are correspondingly bad at exact tokens:
error codes, contract IDs, surnames, version numbers. Two different product names with
similar semantics land in nearly the same place in vector space.

BM25 is the opposite. It's a bag-of-words statistical ranker with no notion of meaning,
which makes it precise on rare exact terms and useless on paraphrase.

Running both and merging covers each one's blind spot. That's the 35% → 49% step. Note
the BM25 index is built over the **contextualised** chunks too — the situating text helps
lexical matching just as much as it helps embeddings.

#### How BM25 actually scores

For each word in the query: **how rare is this word** × **how often does it appear here**,
divided by chunk length. Sum over the query's words.

```
score(chunk, query) =    Σ      IDF(word)  ×   saturating_count(word, chunk)
                    word in query          ──────────────────────────────────
                                                adjusted for chunk length
```

No vectors, no model, no training. Just counting.

A worked example over five chunks (these are real `rank_bm25` outputs — the same library
`answer.py` uses, run through the project's own `tokenize`):

```text
CORPUS (tokenized):
  [0] insurellm was founded in chicago by avery lancaster in 2015
  [1] the apex reinsurance contract renewal premium rose 8 in the second year
  [2] markellm is the marketplace product connecting consumers to insurers
  [3] avery lancaster serves as ceo and was previously at a chicago insurance firm
  [4] the contract includes a standard termination clause and a renewal clause

QUERY: 'Apex renewal premium'

  [1]  2.434 ██████████████    The Apex Reinsurance contract renewal premium rose 8%
  [4]  0.336 ██                The contract includes a standard termination clause…
  [0]  0.000                   Insurellm was founded in Chicago by Avery Lancaster…
  [2]  0.000                   Markellm is the marketplace product connecting…
  [3]  0.000                   Avery Lancaster serves as CEO and was previously…
```

The score is a plain sum over query words, and **rarity dominates**:

```text
  apex      appears in 1/5 chunks → contributes 1.055
  renewal   appears in 2/5 chunks → contributes 0.323
  premium   appears in 1/5 chunks → contributes 1.055
                                    total       2.434
```

Chunk [4] scores slightly above zero only because it also contains "renewal".

#### The three knobs, and what they do

| Part | Effect | Demonstration |
|---|---|---|
| **IDF** (rarity) | Rare words carry the signal; words in most chunks carry ~none | `apex` 1/5 → 1.055 vs `renewal` 2/5 → 0.323 |
| **TF saturation** (`k1=1.5`) | 2nd mention counts, 50th barely does | 1×→3.92, 2×→4.64, 10×→5.46, 50×→5.77 |
| **Length norm** (`b=0.75`) | Short chunks aren't out-competed by padded long ones | identical match: 3-word chunk 8.99, 35-word chunk 2.89 |

Saturation is why keyword stuffing doesn't work: going from 10 to 50 repetitions buys less
than going from 1 to 2 does. The defaults are fine — nobody tunes `k1` and `b`.

> **A gotcha if you experiment with this.** IDF is computed across the corpus, so a term
> appearing in most or all documents scores zero or negative. Toy examples with two or
> three documents produce meaningless numbers; you need a corpus where the query terms
> are genuinely rare before the scores mean anything.

#### The blind spot

This is the entire argument for not shipping BM25 alone. One chunk in a 20-chunk corpus:

```text
  target: "Avery Lancaster serves as Chief Executive Officer of Insurellm."

  FOUND    7.695  'Chief Executive Officer'
  FOUND    5.130  'Avery Lancaster'
  MISSED   0.000  'CEO'
  MISSED   0.000  'who runs the company'
  MISSED   0.000  'who leads the firm'
```

"CEO" *is* what the chunk says. BM25 scores it **zero** — no shared words, no match, and
nothing in the formula has any notion of meaning to bridge the gap.

Embeddings have the mirror-image failure: ask for a specific contract ID or surname and a
semantic model cheerfully returns five *similar-looking* contracts, because they all sit
near each other in vector space.

| Query | BM25 | Voyage embeddings |
|---|---|---|
| "who runs the company" | ✗ no shared words | ✓ semantically close |
| "Apex Reinsurance" | ✓ rare exact tokens | ~ may drift to similar contracts |

Each is blind exactly where the other is sharp. That is the 35% → 49% step, and why
`hybrid_search` runs both rather than picking one.

### 1.5 Fusing two rankings

You cannot simply compare the scores. A cosine similarity lives in `[-1, 1]`; a BM25 score
is unbounded and corpus-dependent. Adding or averaging them is meaningless.

**Reciprocal Rank Fusion** sidesteps this by discarding the scores and using only the
*positions*:

```
RRF(chunk) = Σ  1 / (k + rank_in_list)        k = 60 by convention
          over each list the chunk appears in
```

A chunk found by both retrievers accumulates two contributions and rises above one found
by only one. No calibration, no tuning, no scale mismatch.

### 1.6 Reranking, and the shape of the funnel

Fusion gives a decent ordering, but both retrievers are *bi-encoders*: the query and the
document are embedded separately and never compared directly. A **cross-encoder** reranker
reads the query and each candidate *together* and scores actual relevance. Far more
accurate, far too slow to run over the whole corpus — so it runs over the shortlist.

Anthropic's tested configuration: **retrieve 150 candidates, rerank down to 20**. They
also tested passing 5, 10, and 20 chunks to the model and found **20 performed best** —
worth knowing, since the instinct is usually to pass fewer.

### 1.7 Designing the tool surface

Anthropic's heuristic is *"start with bash for breadth; promote to dedicated tools when you
need to gate, render, audit, or parallelize."* A knowledge-base search is a clear promote:
typed arguments, safe to call repeatedly, and results you want to inspect and log.

The tool's **description is prompt engineering**, not documentation. It's the only thing
Claude sees when deciding whether and how to call it. Describe what the tool is *for*, what
good arguments look like, and when to reach for it.

### 1.8 Model parameters

| Parameter | What it does |
|---|---|
| `thinking={"type": "adaptive"}` | Claude decides *per request* how much to think, and interleaves reasoning between tool calls. Replaces the old fixed `budget_tokens`, which is now rejected on current models. |
| `output_config={"effort": ...}` | `low`→`max`. Trades thoroughness against tokens. Lower effort means fewer, more consolidated tool calls and less preamble. |

Both matter for agentic retrieval specifically: adaptive thinking is what lets Claude
reason about *whether the results it got back are sufficient* before deciding to search
again.

### 1.9 Prompt caching

Caching is a **prefix match** — rendered in the order `tools` → `system` → `messages`. Any
byte change invalidates everything after it. So: stable content first, volatile content
last. A frozen system prompt marked `cache_control` is read from cache on every subsequent
turn of the loop at roughly a tenth of the input cost.

Verify it's working with `usage.cache_read_input_tokens`. If that's zero across repeated
calls, something is silently invalidating the prefix — a timestamp, a UUID, an unsorted
`json.dumps`, a varying tool list.

### 1.10 The embeddings gap

Anthropic's docs state it plainly:

> "Anthropic does not offer its own embedding model."

They recommend **Voyage AI**. This implementation uses `voyage-4` for embeddings and
`rerank-2.5` for reranking. So a "pure Anthropic stack" RAG system is necessarily
two vendors: Anthropic for reasoning, Voyage for vector operations.

---

## Part 2 — The implementation

```
claude_implementation/
├── ingest.py    documents → contextualised chunks → Chroma (dense) + pickle (BM25)
├── answer.py    question → agentic loop over hybrid search → answer
├── README.md    design summary
└── TUTORIAL.md  this file
```

### 2.0 The data flow, and what lives where

```
INGEST
  documents → chunks → prepend situating context
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
       Voyage embeds text            tokenise into words
              ▼                             ▼
    Chroma: vector + text + meta    pickle: text + meta
         (../claude_db)              (../claude_bm25.pkl)
              └───── no link between them ─────┘

RETRIEVAL  (per search the agent makes)
  query ──┬─► embed query → Chroma nearest-neighbour  → 150 chunks ─┐
          └─► tokenise query → BM25 scores            → 150 chunks ─┤
                                                                    ▼
                                                      RRF fusion (merge by rank)
                                                                    ▼
                                                    Voyage rerank-2.5 → top 20
```

Four things in that picture are easy to get wrong:

**The two stores are independent.** Chroma does not reference the pickle and the
pickle does not reference Chroma. They are two parallel indexes over the same chunks,
and the chunk text is stored in full in *both*:

```python
collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)
#                                            ↑ full chunk text, in Chroma

payload = {
    "texts": [chunk.page_content for chunk in chunks],   # ← full chunk text again,
    "metadatas": [chunk.metadata for chunk in chunks],   #   this time in the pickle
}
```

Delete the pickle and dense search still works — that is exactly the "using dense
search only" path `bm25()` warns about.

**BM25 embeds nothing.** It has no vectors. It tokenises text into words and scores
by word rarity and frequency. That is the whole reason it's worth running alongside
Voyage: no vectors means it fails on entirely different queries than an embedding
model does.

**One pickle, loaded once.** A single file for the whole knowledge base, written at the
end of ingest — not one per chunk. It is read once per *process*, not once per search:
the agent may search a dozen times to answer one question, and `bm25()` caches the
rebuilt index across all of them.

**"Contextual" describes ingest, not ranking.** Voyage ranks by semantic similarity,
plain and simple. The situating context is baked into the chunk text *before* embedding;
by query time it is just part of the chunk like any other words.

Everything below the dotted line in that diagram is **one** search. How many searches
happen is Claude's decision — see §2.6.

### 2.1 Contextual chunking

One structured call per document. Claude splits it *and* situates every chunk, with the
whole document in view:

```python
class Chunk(BaseModel):
    context: str = Field(
        description=(
            "A short succinct context, 50-100 tokens, that situates this chunk within the "
            "overall document for the purposes of improving search retrieval of the chunk. "
            "Name the company, people, product or contract the chunk is about, so the chunk "
            "can be understood on its own without the rest of the document."
        )
    )
    original_text: str = Field(
        description="The original text of this chunk from the provided document, exactly as is, not changed in any way"
    )

    def as_result(self, document):
        metadata = {"source": document["source"], "type": document["type"]}
        # The situating context is prepended so it is embedded and BM25-indexed
        # together with the chunk - that is the whole point of the technique.
        return Result(
            page_content=self.context + "\n\n" + self.original_text,
            metadata=metadata,
        )
```

The `Field(description=...)` text is not a comment — it's shipped to Claude as the JSON
schema, so it functions as a per-field instruction.

### 2.2 Structured outputs

`messages.parse` with `output_format=<pydantic model>` returns a validated object rather
than a string you have to parse and defend against:

```python
response = client().messages.parse(
    model=MODEL,                                   # claude-opus-5
    max_tokens=16000,
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    thinking={"type": "adaptive"},
    output_config={"effort": "medium"},
    messages=[{"role": "user", "content": make_prompt(document)}],
    output_format=Chunks,
)
return [chunk.as_result(document) for chunk in response.parsed_output.chunks]
```

**A deliberate deviation:** Anthropic's write-up makes one API call *per chunk* against a
cached document. This makes one call *per document* returning all its chunks. Each chunk
still gets full whole-document visibility — the property the technique depends on — at a
fraction of the request count. For a knowledge base of this size that trade is clearly
right; for very long documents, per-chunk calls give the model more room to attend to each
chunk individually.

### 2.3 Two indexes from one chunk set

Dense vectors go to Chroma, batched (a single request would exceed Voyage's per-call input
limit on a large corpus):

```python
def embed(texts):
    voyage = voyageai.Client()
    vectors = []
    for start in tqdm(range(0, len(texts), EMBED_BATCH_SIZE), desc="Embedding"):
        vectors.extend(embed_batch(voyage, texts[start : start + EMBED_BATCH_SIZE]))
    return vectors
```

Note `input_type="document"` at ingest and `input_type="query"` at search time. Voyage
prepends different internal prompts for each, and using the right one measurably improves
retrieval. It's easy to miss.

The lexical side pickles the **corpus**, not the index object:

```python
def create_bm25_index(chunks):
    """Save the chunk text to disk so answer.py can run keyword search over it.

    Note what gets saved: the plain text, not the finished BM25 index. The index
    is rebuilt from that text when answer.py loads it.

    Saving the index object itself would be easy - pickle can do it - but the
    file would then be tied to the exact rank_bm25 version that wrote it. After a
    library upgrade it might still load without complaining and quietly score
    things wrong, which is the kind of bug that never shows up in a log. A list
    of plain strings can't rot that way, and rebuilding is only word counting.
    """
    payload = {
        "texts": [chunk.page_content for chunk in chunks],
        "metadatas": [chunk.metadata for chunk in chunks],
    }
    with open(BM25_PATH, "wb") as f:
        pickle.dump(payload, f)
```

Also note the ordering inside `create_embeddings`: embeddings are computed **before** the
old collection is deleted, so a failed API call doesn't leave you with no knowledge base.

### 2.4 The search tool

```python
@beta_tool
def search_knowledge_base(query: str, n_results: int = FINAL_K) -> str:
    """Search Insurellm's internal knowledge base and return the most relevant extracts.

    Args:
        query: What to look for, as a natural-language question or phrase. Specific names,
            products and contract titles retrieve better than generic wording.
        n_results: How many extracts to return. Defaults to 20; raise it for a broad survey
            question, lower it when you only need one specific fact.
    """
    chunks = hybrid_search(query, max(1, min(n_results, FINAL_K)))
    ...
```

`@beta_tool` generates the JSON schema from the type hints and the Google-style docstring —
the `Args:` entries become per-parameter `description` fields. **The docstring is the
prompt.** Note `max(1, min(n_results, FINAL_K))`: the model supplies that argument, so it
gets clamped rather than trusted.

Results are wrapped in tagged blocks so Claude can attribute claims:

```python
f"<extract source=\"{chunk.metadata.get('source', 'unknown')}\">\n{chunk.page_content}\n</extract>"
```

And an empty result set returns *instructions*, not silence:

```python
return "No matching extracts found in the knowledge base. Try different wording."
```

That sentence is what turns a dead end into another attempt.

### 2.5 Hybrid search

```python
def hybrid_search(query, n=FINAL_K):
    """Dense + lexical, fused, then reranked down to n."""
    dense = dense_search(query, RETRIEVAL_K)      # 150 via Voyage + Chroma
    lexical = lexical_search(query, RETRIEVAL_K)  # 150 via BM25
    fused = reciprocal_rank_fusion([dense, lexical])
    return rerank(query, fused[:RETRIEVAL_K], n)  # → 20 via rerank-2.5
```

Fusion, deduplicating on chunk text:

```python
def reciprocal_rank_fusion(rankings, k=60):
    scores = {}
    chunks = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            key = chunk.page_content
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            chunks.setdefault(key, chunk)
    order = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [chunks[key] for key in order]
```

If BM25 hasn't been built, `lexical_search` returns `[]` and the system degrades to
dense-only with a warning rather than crashing.

### 2.6 The agent loop

```python
runner = client.beta.messages.tool_runner(
    model=MODEL,
    max_tokens=16000,
    system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
    thinking={"type": "adaptive"},
    output_config={"effort": "high"},
    tools=[search_knowledge_base],
    messages=messages,
    max_iterations=MAX_ITERATIONS,
)
```

`tool_runner` drives request → tool call → execute → feed result back → repeat, until
Claude stops calling tools. You write the tool; the SDK writes the loop.

**One sharp edge.** A turn can come back with `stop_reason == "pause_turn"`. The Python
runner exits when no client tool ran — so a paused turn ends the loop and is returned as
the final message with **no error and no warning**, just a truncated answer. The fix is to
mirror the history and restart the runner on the paused turn:

```python
    last = None
    for message in runner:
        last = message
        messages.append({"role": "assistant", "content": message.content})
        tool_response = runner.generate_tool_call_response()
        if tool_response is not None:
            messages.append(tool_response)

    if last is None or last.stop_reason != "pause_turn":
        break
    restarts += 1
    if restarts > MAX_RESTARTS:
        raise RuntimeError(f"turn still paused after {MAX_RESTARTS} restarts")
```

### 2.7 Reporting what the agent retrieved

`answer_question` must return the chunks used — but in an agent loop, *which* chunks those
are is only known after the fact. A `ContextVar` collects them:

```python
_retrieved: ContextVar[list] = ContextVar("retrieved")

def answer_question(question: str, history: list[dict] | None = None) -> tuple[str, list]:
    history = [] if history is None else history
    messages = list(history) + [{"role": "user", "content": question}]

    collected: list = []
    token = _retrieved.set(collected)
    try:
        answer = run_agent(messages)
    finally:
        _retrieved.reset(token)
    return answer, collected
```

A plain module global would work until two callers run concurrently — a Gradio app serving
two users, or a parallel evaluation run — and then they'd silently collect each other's
chunks. A `ContextVar` is per-execution-context, so each call sees only its own.

### 2.8 One thing deliberately *not* done

```python
def run_agent(messages):
    """...
    Deliberately not wrapped in @retry: re-running this replays every tool call and
    every LLM call in the loop, and `messages` has already been extended with the
    partial transcript, so a retry would resume from a half-built conversation.
    """
```

This was a real bug during development, caught by a test that expected 4 runner starts and
got 20. Retry belongs on individual API calls, not around a loop that mutates state and
spends money on every iteration.

---

## Part 3 — Differences from `pro_implementation`

### 3.1 Side by side

| | `pro_implementation` | `claude_implementation` |
|---|---|---|
| Answering model | `groq/openai/gpt-oss-120b` | `claude-opus-5` |
| Ingest model | `openai/gpt-4.1-nano` | `claude-opus-5` |
| SDK | `litellm` (multi-provider) | `anthropic` ≥1.5 |
| Embeddings | OpenAI `text-embedding-3-large` (3072-d) | Voyage `voyage-4` (1024-d) |
| Lexical index | none | BM25 over contextualised chunks |
| Reranker | LLM asked to output a ranked id list | Voyage `rerank-2.5` cross-encoder |
| What's indexed | headline + summary + text | **situating context** + text |
| Retrieval control | fixed pipeline | **Claude decides, via a tool** |
| Query handling | explicit `rewrite_query` LLM call | Claude phrases its own queries |
| Funnel | 20 → 10 | **150 → 20** |
| Vector store | `../preprocessed_db` | `../claude_db` |

### 3.2 The differences that actually matter

**1 — Who decides what to retrieve.** This is the big one. `pro_implementation` runs a
fixed sequence: rewrite the question, retrieve for the original, retrieve for the rewrite,
merge, rerank, answer. Exactly two retrievals, always, whatever the question. Here, Claude
issues searches until it can answer — one for a simple lookup, four or five for a
multi-part question, and it can use what it learned in search #1 to phrase search #2.

**2 — What goes into the index.** Both ask an LLM to enrich chunks before embedding, which
makes them look similar. They aren't. `pro_implementation` generates a `headline` and
`summary` *of the chunk* — derived from the chunk's own content, so it adds little the
chunk didn't already say. This generates a `context` describing *where the chunk sits in
the document* — information the chunk provably does not contain. That's the difference
between paraphrase and Contextual Retrieval, and it's where the measured 35% comes from.

**3 — One retriever or two.** `pro_implementation` is dense-only; it runs two *queries*
against one embedding index, which doesn't help with exact-token queries, because both
queries hit a retriever with the same blind spot. Adding BM25 covers a different failure
mode entirely.

**4 — How candidates get ranked.** `pro_implementation` pastes the chunks into a prompt and
asks the LLM to return a reordered list of ids. This works but is fragile — the model can
return out-of-range ids, duplicate them, or omit some (all three are defended against in
`reorder_chunks`). A purpose-built cross-encoder returns scored indices, costs a fraction
as much, and can't hallucinate an id.

**5 — Scale.** 20→10 versus 150→20. The wider funnel is only affordable *because* the
reranker is cheap; you would not paste 150 chunks into an LLM reranker prompt.

### 3.3 What `pro_implementation` does better

Be fair about this:

- **Provider independence.** `litellm` means switching to any model is a one-line change.
  This implementation is committed to Anthropic + Voyage.
- **Predictable cost and latency.** A fixed pipeline makes exactly N calls. An agent loop
  makes somewhere between 2 and `MAX_ITERATIONS`, and you don't know which in advance.
- **Explicit query rewriting.** `rewrite_query` is inspectable and testable in isolation.
  Here that behaviour is implicit in Claude's judgement — better when it works, harder to
  debug when it doesn't.
- **Simplicity.** It's a shorter, flatter program with fewer moving parts and one vendor.

### 3.4 The honest trade

| | Fixed pipeline | Agentic |
|---|---|---|
| Simple factual question | Fast, cheap, correct | Same answer, more tokens |
| Multi-hop question | One blurred retrieval | Decomposes it |
| Cost per question | Predictable | Variable |
| Failure mode | Retrieves the wrong thing, answers anyway | May loop, or stop early |

The agent earns its cost on questions whose retrieval shape isn't knowable up front. On
everything else it's paying for flexibility it doesn't use.

---

## Part 4 — Running it

```bash
# .env needs both:
#   ANTHROPIC_API_KEY=...
#   VOYAGE_API_KEY=...

cd week5/claude_implementation
python ingest.py          # builds ../claude_db and ../claude_bm25.pkl
```

Then from `week5/`:

```python
from claude_implementation.answer import answer_question

answer, chunks = answer_question("Who won the IIOTY award?")
```

The public API matches the sibling implementations, so `app.py` and `evaluation/eval.py`
work by changing only the import:

- `answer_question(question, history) -> (answer, chunks)` — `chunks` is everything the
  agent retrieved across all its searches, deduplicated.
- `fetch_context(question, history) -> chunks` — one direct hybrid search, bypassing the
  agent, so retrieval quality can be measured independently of answer quality.

## Part 5 — Gotchas

| Gotcha | Why |
|---|---|
| Separate `claude_db` | Voyage is 1024-d, OpenAI is 3072-d — they cannot share a Chroma collection. |
| Needs `anthropic>=1.5` | The 0.x SDK has no `output_config`/`effort` and no `messages.parse`. |
| `input_type` on every Voyage call | `"document"` at ingest, `"query"` at search. Silently worse retrieval if wrong. |
| `pause_turn` | The Python tool runner exits instead of resuming; truncates answers silently. |
| Don't `@retry` the agent loop | Replays every tool call against a half-built transcript. |
| Check `cache_read_input_tokens` | Zero means something is invalidating the cached prefix. |

## Glossary

| Term | Meaning |
|---|---|
| **Contextual Retrieval** | Prepending model-generated, whole-document-aware context to each chunk before indexing. |
| **BM25** | A bag-of-words lexical ranker. Precise on rare exact terms, blind to meaning. |
| **Bi-encoder** | Query and document embedded separately, compared by vector distance. Fast, less accurate. |
| **Cross-encoder** | Query and document read together and scored. Accurate, too slow for full-corpus search. |
| **RRF** | Reciprocal Rank Fusion — merges ranked lists using positions, not scores. |
| **Adaptive thinking** | Claude decides per request how much to reason; replaces fixed `budget_tokens`. |
| **Effort** | `low`→`max` knob trading thoroughness against token spend. |
| **`pause_turn`** | A stop reason meaning the turn was interrupted and needs resuming. |
| **Prompt caching** | Prefix-matched reuse of stable request content at ~10% of input cost. |

## Sources

- [Introducing Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) — the technique and all failure-rate numbers
- [Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings) — "Anthropic does not offer its own embedding model"
- [Building effective agents](https://www.anthropic.com/research/building-effective-agents) — the tier model and the four criteria
