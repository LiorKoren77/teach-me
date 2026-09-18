You split textbook pages into overlapping chunks for a retrieval index, following the contextual retrieval technique: a chunk that cannot be understood on its own cannot be retrieved on its own, so every chunk gets a short situating context.

The pages belong to the subject "{subject}", from the source "{source}". They are wrapped in <page index="N" printed="P"> tags. Pages inside <context_before> and <context_after> are for orientation only: do not produce chunks from them.

For each chunk produce:
1. original_text: verbatim text copied from the batch pages, unchanged. Together the chunks must cover every batch page completely; leave nothing out. Overlap neighbouring chunks by roughly a quarter so the same sentence appears in two chunks where a topic continues. Aim for chunks of 100 to 300 words that can each answer a specific question alone.
2. context: 50 to 100 tokens, written in the language of the source text, situating the chunk within the source: the chapter or section it belongs to, the concept it discusses, and the named places, people, dates and figures it refers to. It orients a reader who sees only this chunk. Do not summarize the chunk itself.
3. page_start and page_end: the index attributes of the first and last page the original_text spans.

Figure blocks (lines beginning with "> **[Figure") are part of the page text and must be included in chunks like any other text.
