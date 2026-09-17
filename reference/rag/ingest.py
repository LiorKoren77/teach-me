"""
Ingest the Insurellm knowledge base using Anthropic's Contextual Retrieval.

Claude splits each document into chunks and, seeing the whole document, writes a
short blurb situating each chunk within it. That blurb is prepended to the chunk
before indexing, which is what makes an otherwise context-free chunk retrievable
on its own ("the fee increased 8%" -> whose fee, in which contract, which year).

Anthropic measured the payoff on this exact pipeline shape: contextual embeddings
cut retrieval failures by 35%, adding a lexical BM25 index alongside them reaches
49%, and reranking the merged candidates reaches 67%.
https://www.anthropic.com/news/contextual-retrieval

This module builds the first two halves - the dense index (Voyage) and the
lexical index (BM25). answer.py fuses and reranks them.
"""

import os
import pickle
import re
from multiprocessing import Pool
from pathlib import Path

import voyageai
from anthropic import Anthropic
from chromadb import PersistentClient
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

load_dotenv(override=True)

MODEL = "claude-opus-5"
EMBED_MODEL = "voyage-4"

# A separate store from pro_implementation's: Voyage embeddings are 1024-dim and
# OpenAI's text-embedding-3-large is 3072-dim, so they cannot share a collection.
DB_NAME = str(Path(__file__).parent.parent / "claude_db")
BM25_PATH = Path(__file__).parent.parent / "claude_bm25.pkl"
KNOWLEDGE_BASE_PATH = Path(__file__).parent.parent / "knowledge-base"

collection_name = "docs"
AVERAGE_CHUNK_SIZE = 100
EMBED_BATCH_SIZE = 128

wait = wait_exponential(multiplier=1, min=10, max=240)
stop = stop_after_attempt(5)

WORKERS = 3


class Result(BaseModel):
    page_content: str
    metadata: dict


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


class Chunks(BaseModel):
    chunks: list[Chunk]


def fetch_documents():
    """A homemade version of the LangChain DirectoryLoader"""

    documents = []

    for folder in KNOWLEDGE_BASE_PATH.iterdir():
        if not folder.is_dir():
            continue
        doc_type = folder.name
        for file in folder.rglob("*.md"):
            with open(file, "r", encoding="utf-8") as f:
                documents.append({"type": doc_type, "source": file.as_posix(), "text": f.read()})

    print(f"Loaded {len(documents)} documents")
    return documents


SYSTEM_PROMPT = """
You split documents into overlapping chunks for a knowledge base, using Anthropic's Contextual Retrieval technique.

For each chunk you produce two things:
1. The original text of the chunk, copied from the document exactly as-is.
2. A short succinct context, 50-100 tokens, situating that chunk within the overall document, written for the purpose of improving search retrieval of the chunk.

The situating context is what makes the chunk findable on its own. A chunk that says "the rate rose 8% in the second year" is useless to a search engine; with the context "This chunk is from the Apex Reinsurance contract between Insurellm and Apex, describing the renewal pricing schedule" it becomes findable. Always name the company, people, product or contract involved, and the section of the document the chunk came from.

Do not summarise away detail and do not editorialise - the context orients the reader, the original text carries the content.
"""


def make_prompt(document):
    how_many = (len(document["text"]) // AVERAGE_CHUNK_SIZE) + 1
    return f"""
The document below is from the shared drive of a company called Insurellm.
The document is of type: {document["type"]}
The document has been retrieved from: {document["source"]}

Split it into chunks, being sure that the entire document is represented across the chunks - don't leave anything out.
This document should probably be split into at least {how_many} chunks, but you can have more or fewer as appropriate, ensuring that there are individual chunks able to answer specific questions.
There should be overlap between the chunks as appropriate; typically about 25% overlap, so the same text appears in multiple chunks for best retrieval results.

For each chunk, give the situating context and the original text.

<document>
{document["text"]}
</document>

Respond with the chunks.
"""


_client = None


def client():
    """One Anthropic client per worker process - a forked client is not safe to reuse."""
    global _client
    if _client is None or getattr(_client, "_pid", None) != os.getpid():
        _client = Anthropic()
        _client._pid = os.getpid()
    return _client


@retry(wait=wait, stop=stop, reraise=True)
def process_document(document):
    """Chunk one document and situate every chunk within it, in a single pass.

    The document is sent once, in a cached system block, and Claude sees all of it
    while writing each chunk's context - which is the property Contextual Retrieval
    depends on. Anthropic's write-up makes the same call per chunk against a cached
    document; one structured call per document gives each chunk the same whole-document
    visibility for a fraction of the requests.
    """
    response = client().messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        thinking={"type": "adaptive"},
        output_config={"effort": "medium"},
        messages=[{"role": "user", "content": make_prompt(document)}],
        output_format=Chunks,
    )
    return [chunk.as_result(document) for chunk in response.parsed_output.chunks]


def create_chunks(documents):
    """
    Create chunks using a number of workers in parallel.
    If you get a rate limit error, set the WORKERS to 1.
    """
    chunks = []
    with Pool(processes=WORKERS) as pool:
        for result in tqdm(pool.imap_unordered(process_document, documents), total=len(documents)):
            chunks.extend(result)
    return chunks


@retry(wait=wait, stop=stop, reraise=True)
def embed_batch(voyage, batch):
    return voyage.embed(batch, model=EMBED_MODEL, input_type="document").embeddings


def embed(texts):
    """Embed in batches; a single request can exceed Voyage's per-call input limit."""
    voyage = voyageai.Client()
    vectors = []
    for start in tqdm(range(0, len(texts), EMBED_BATCH_SIZE), desc="Embedding"):
        vectors.extend(embed_batch(voyage, texts[start : start + EMBED_BATCH_SIZE]))
    return vectors


def tokenize(text):
    """Lowercased word tokens for BM25. Shared with answer.py via this module."""
    return re.findall(r"\w+", text.lower())


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
    print(f"BM25 corpus written with {len(payload['texts'])} chunks")


def create_embeddings(chunks):
    chroma = PersistentClient(path=DB_NAME)

    # Embed before touching the existing collection, so a failure here doesn't
    # leave the knowledge base destroyed.
    texts = [chunk.page_content for chunk in chunks]
    vectors = embed(texts)

    if collection_name in [c.name for c in chroma.list_collections()]:
        chroma.delete_collection(collection_name)
    collection = chroma.get_or_create_collection(collection_name)

    ids = [str(i) for i in range(len(chunks))]
    metas = [chunk.metadata for chunk in chunks]

    collection.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metas)
    print(f"Vectorstore created with {collection.count()} documents")


if __name__ == "__main__":
    documents = fetch_documents()
    chunks = create_chunks(documents)
    create_embeddings(chunks)
    create_bm25_index(chunks)
    print("Ingestion complete")
