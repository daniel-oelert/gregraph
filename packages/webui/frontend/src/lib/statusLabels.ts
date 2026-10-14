/**
 * Status lists (pending / outdated / stale) carry link labels formatted by the backend as
 * "SOURCE TYPE TARGET" (space separated), or bare document IDs. Only the SOURCE is a document
 * to open. Patterns mirror core `ids.ID_PATTERN` (spec 4.1, uppercase canonical form) and the
 * edge type slug (spec 5.3).
 */
const DOC_ID = /^[A-Z][A-Z0-9]{0,7}-[0-9A-HJKMNP-TV-Z]{6}$/;
const EDGE_TYPE = /^[a-z][a-z0-9-]*$/;

export type ParsedStatusLabel =
  | { kind: "document"; id: string }
  | { kind: "link"; source: string; type: string; target: string };

/**
 * Parses one status-list entry. Returns null for anything that is not a canonical link label
 * or a canonical bare ID, so malformed entries are shown as text and never used as an ID.
 */
export function parseStatusLabel(label: string): ParsedStatusLabel | null {
  const parts = label.split(" ");
  if (parts.length === 1) {
    return DOC_ID.test(label) ? { kind: "document", id: label } : null;
  }
  if (parts.length !== 3) {
    return null;
  }
  const [source, type, target] = parts as [string, string, string];
  if (!DOC_ID.test(source) || !EDGE_TYPE.test(type) || !DOC_ID.test(target)) {
    return null;
  }
  return { kind: "link", source, type, target };
}
