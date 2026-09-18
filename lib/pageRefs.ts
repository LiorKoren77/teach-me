// The teaching text points at source pages in prose ("see page 12"). A part the backend has
// rendered with `page_refs` says which pages it means; one rendered before that field existed
// does not, and the reader derives them from the body instead. One pattern per taught language;
// matches are returned once each, in the order they appear.
const PAGE_WORDS = /(?:pages?|עמודים|עמוד|páginas?|paginas?)\s*(\d{1,4})/gi;

export function extractPageRefs(body: string): number[] {
  const found: number[] = [];
  for (const match of body.matchAll(PAGE_WORDS)) {
    const page = Number(match[1]);
    if (!found.includes(page)) found.push(page);
  }
  return found;
}

/**
 * The pages to show thumbnails for: the global 0-based indices the backend served with the part,
 * or the prose scan when it served none. An empty `page_refs` is an answer, not a gap - the part
 * refers to no page - so it is kept as it is.
 */
// TODO(stage 4): remove fallback once page_refs is mandatory
export function pageRefsOf(part: { body: string; page_refs?: number[] } | null | undefined): number[] {
  if (!part) return [];
  return part.page_refs ?? extractPageRefs(part.body);
}
