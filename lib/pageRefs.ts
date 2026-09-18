// The teaching text points at source pages in prose ("see page 12"); the backend does not yet
// return structured page references, so the reader derives them from the body. One pattern per
// taught language; matches are returned once each, in the order they appear.
const PAGE_WORDS = /(?:pages?|עמודים|עמוד|páginas?|paginas?)\s*(\d{1,4})/gi;

export function extractPageRefs(body: string): number[] {
  const found: number[] = [];
  for (const match of body.matchAll(PAGE_WORDS)) {
    const page = Number(match[1]);
    if (!found.includes(page)) found.push(page);
  }
  return found;
}
