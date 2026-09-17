"""
Answer questions about Insurellm with an agentic RAG loop driven by Claude.

Rather than a fixed retrieve-then-answer pipeline, Claude is given a
search_knowledge_base tool and decides for itself what to look up, reads what
comes back, and searches again when a question needs more than one hop
("who studied at Manchester and what do they work on now?").

Each search is hybrid, following Anthropic's Contextual Retrieval findings:
a dense Voyage search and a lexical BM25 search run over the same contextualised
chunks, their rankings are fused with Reciprocal Rank Fusion, and Voyage's
reranker picks the final set. Anthropic found 20 chunks to outperform 5 or 10,
and reranking the merged candidates to be worth a further 18 points of
failure-rate reduction.
"""

import pickle
from contextvars import ContextVar

import voyageai
from anthropic import Anthropic, beta_tool
from chromadb import PersistentClient
from dotenv import load_dotenv
from pydantic import BaseModel
from rank_bm25 import BM25Okapi
from tenacity import retry, stop_after_attempt, wait_exponential

from .ingest import BM25_PATH, DB_NAME, EMBED_MODEL, collection_name, tokenize

load_dotenv(override=True)

MODEL = "claude-opus-5"
RERANK_MODEL = "rerank-2.5"

# Anthropic's numbers: 150 candidates in, reranked down to 20 for the model.
RETRIEVAL_K = 150
FINAL_K = 20
MAX_ITERATIONS = 12
MAX_RESTARTS = 3

wait = wait_exponential(multiplier=1, min=10, max=240)
stop = stop_after_attempt(5)

SYSTEM_PROMPT = """
You are a knowledgeable, friendly assistant representing the company Insurellm, chatting with a user about the company.

You have a search_knowledge_base tool over Insurellm's internal shared drive - its contracts, product docs, employee records and company pages. You cannot see any of it until you search, so search before you answer.

How to use it well:
- Search first, always. Never answer about Insurellm from memory; you have none.
- Use the user's own vocabulary in your first query, then follow up with the specific names, products or contracts you learned from the results.
- A question with several parts needs several searches. Look up each part, then answer once you have all of it.
- If results come back thin or off-target, rephrase and search again rather than guessing.
- Stop searching once you can fully answer.

Your answer will be evaluated for accuracy, relevance and completeness, so make sure it only answers the question asked, and answers it fully. Ground every claim in what the search returned, and name the source document when it helps. If the knowledge base does not contain the answer, say so plainly rather than inventing one.
"""


class Result(BaseModel):
    page_content: str
    metadata: dict


# Chunks retrieved during one answer_question call. A ContextVar rather than a
# global so concurrent callers (gradio, the evaluator) don't collect each other's.
_retrieved: ContextVar[list] = ContextVar("retrieved")

_voyage = None
_collection = None
_bm25 = None
_bm25_corpus = None


def voyage():
    global _voyage
    if _voyage is None:
        _voyage = voyageai.Client()
    return _voyage


def collection():
    global _collection
    if _collection is None:
        chroma = PersistentClient(path=DB_NAME)
        _collection = chroma.get_or_create_collection(collection_name)
        if _collection.count() == 0:
            print(f"WARNING: collection '{collection_name}' in {DB_NAME} is empty - run ingest.py first")
    return _collection


def bm25():
    """Load the saved chunk text and build the BM25 keyword index from it.

    ingest.py saves only the text, so the index is built here rather than loaded
    (see create_bm25_index for why). Done once per process and kept: the agent may
    search a dozen times to answer one question, and rebuilding - or re-printing
    the missing-file warning - on every one of those would be wasteful.
    """
    global _bm25, _bm25_corpus
    if _bm25_corpus is None:
        if not BM25_PATH.exists():
            print(f"WARNING: {BM25_PATH} not found - run ingest.py first; using dense search only")
            _bm25_corpus = {"texts": [], "metadatas": []}
        else:
            with open(BM25_PATH, "rb") as f:
                _bm25_corpus = pickle.load(f)
            _bm25 = BM25Okapi([tokenize(text) for text in _bm25_corpus["texts"]])
    return _bm25, _bm25_corpus


@retry(wait=wait, stop=stop, reraise=True)
def dense_search(query, k):
    """Voyage-embedded nearest neighbours from Chroma."""
    embedding = voyage().embed([query], model=EMBED_MODEL, input_type="query").embeddings[0]
    results = collection().query(query_embeddings=[embedding], n_results=k)
    return [
        Result(page_content=text, metadata=meta)
        for text, meta in zip(results["documents"][0], results["metadatas"][0])
    ]


def lexical_search(query, k):
    """BM25 over the same contextualised chunks - catches exact names and codes
    that a dense embedding blurs together."""
    index, corpus = bm25()
    if index is None:
        return []
    scores = index.get_scores(tokenize(query))
    top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [
        Result(page_content=corpus["texts"][i], metadata=corpus["metadatas"][i])
        for i in top
        if scores[i] > 0
    ]


def reciprocal_rank_fusion(rankings, k=60):
    """Fuse ranked lists by summing 1/(k+rank), deduplicating on chunk text.

    RRF needs no score calibration between the two retrievers, which matters here
    because a cosine similarity and a BM25 score are not on comparable scales.
    """
    scores = {}
    chunks = {}
    for ranking in rankings:
        for rank, chunk in enumerate(ranking):
            key = chunk.page_content
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            chunks.setdefault(key, chunk)
    order = sorted(scores, key=lambda key: scores[key], reverse=True)
    return [chunks[key] for key in order]


@retry(wait=wait, stop=stop, reraise=True)
def rerank(query, chunks, n):
    """Voyage cross-encoder rerank - the step Anthropic measured as worth a
    further 18 points of failure-rate reduction on top of hybrid retrieval."""
    if not chunks:
        return []
    documents = [chunk.page_content for chunk in chunks]
    reranking = voyage().rerank(query=query, documents=documents, model=RERANK_MODEL, top_k=n)
    return [chunks[item.index] for item in reranking.results]


def hybrid_search(query, n=FINAL_K):
    """Dense + lexical, fused, then reranked down to n."""
    dense = dense_search(query, RETRIEVAL_K)
    lexical = lexical_search(query, RETRIEVAL_K)
    fused = reciprocal_rank_fusion([dense, lexical])
    return rerank(query, fused[:RETRIEVAL_K], n)


def format_chunks(chunks):
    if not chunks:
        return "No matching extracts found in the knowledge base. Try different wording."
    return "\n\n".join(
        f"<extract source=\"{chunk.metadata.get('source', 'unknown')}\">\n{chunk.page_content}\n</extract>"
        for chunk in chunks
    )


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
    collected = _retrieved.get(None)
    if collected is not None:
        seen = {chunk.page_content for chunk in collected}
        collected.extend(chunk for chunk in chunks if chunk.page_content not in seen)
    return format_chunks(chunks)


def fetch_context(question: str, history: list[dict] | None = None) -> list:
    """Retrieve for a question directly, without the agent loop.

    Kept so retrieval can be measured on its own (evaluation/eval.py does exactly
    this); the agent's own retrieval is what answer_question returns.
    """
    return hybrid_search(question, FINAL_K)


def run_agent(messages):
    """Drive the tool-use loop and return the final answer text.

    Deliberately not wrapped in @retry: re-running this replays every tool call and
    every LLM call in the loop, and `messages` has already been extended with the
    partial transcript, so a retry would resume from a half-built conversation. The
    SDK retries transient HTTP failures itself, and the retrieval calls underneath
    carry their own bounded retries - this layer should fail fast instead.

    The Python tool runner exits when a turn comes back as pause_turn rather than
    resuming it, which would silently truncate the answer - so the history is
    mirrored here and the runner restarted on the paused turn.
    """
    client = Anthropic()
    messages = list(messages)
    restarts = 0
    while True:
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

    if last is None:
        return ""
    return "\n".join(block.text for block in last.content if block.type == "text").strip()


def answer_question(question: str, history: list[dict] | None = None) -> tuple[str, list]:
    """
    Answer a question using agentic RAG and return the answer and the retrieved context
    """
    history = [] if history is None else history
    messages = list(history) + [{"role": "user", "content": question}]

    collected: list = []
    token = _retrieved.set(collected)
    try:
        answer = run_agent(messages)
    finally:
        _retrieved.reset(token)
    return answer, collected
