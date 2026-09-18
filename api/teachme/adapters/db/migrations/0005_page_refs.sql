-- Teaching content says which pages its figures are on, as global corpus indices: the same
-- numbers GET /api/subjects/{id}/pages/{index}/image takes. Existing rows get the empty array,
-- which is what a part whose text points at no figure legitimately stores.
ALTER TABLE part_content ADD COLUMN page_refs integer[] NOT NULL DEFAULT '{}';
