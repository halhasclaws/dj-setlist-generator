// Matching for the private collection's entries in the header search panel.
// Pure: the route authorizes and loads names; this only decides what matches.
import { sortByLineup } from "./lineup";
import { YOON_COLLECTION_HREF, yoonSetHref } from "./collection-summary";

export type YoonSearchName = { id: string; slug: string; title: string; performer: string | null; imageUrl: string | null };

export type YoonSearchResult = {
  href: string;
  id: string;
  imageUrl: string | null;
  kind: "collection" | "set";
  meta: string;
  name: string;
  slug: string;
};

export type YoonSearchPayload = { query: string; results: YoonSearchResult[] };

const COLLECTION_TERMS = ["yoon", "fest", "festival", "yoonfest"];
export const YOON_COLLECTION_NAME = "Yoon Fest";

/** Lower-case, accents removed ("Honeydü" -> "honeydu"), punctuation to spaces. */
export const normalizeSearchText = (value: string) => value.normalize("NFKD").replace(/\p{M}/gu, "")
  .toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

const tokensOf = (value: string) => normalizeSearchText(value).split(" ").filter(Boolean);

const isCollectionToken = (token: string) => COLLECTION_TERMS.some((term) => term.startsWith(token));

/**
 * "yoon", "yoon fest", "Yoon Fest Jackson" and "fest" name the collection; any
 * other words narrow its sets by lineup name or performer. Without collection
 * words, sets match on every word ("jackson", "adam rose").
 */
export function matchYoonSearch(query: string, names: readonly YoonSearchName[]): YoonSearchResult[] {
  const tokens = tokensOf(query);
  if (tokens.length === 0 || normalizeSearchText(query).replace(/ /g, "").length < 2) return [];
  // A collection word only counts as one when it is clearly meant: "yo"+, or a whole word like "fest".
  const namesCollection = tokens.some((token) => isCollectionToken(token) && (token.startsWith("yo") || token.length >= 4));
  const remaining = namesCollection ? tokens.filter((token) => !isCollectionToken(token)) : tokens;
  const ordered = sortByLineup(names);
  const sets = ordered.filter((set) => {
    const haystack = normalizeSearchText([set.title, set.performer ?? ""].join(" "));
    return remaining.every((token) => haystack.includes(token));
  });
  if (!namesCollection && sets.length === 0) return [];
  return [{
    href: YOON_COLLECTION_HREF, id: "yoon-fest", imageUrl: null, kind: "collection",
    meta: `Private collection - ${names.length} sets`, name: YOON_COLLECTION_NAME, slug: "yoon-fest",
  }, ...sets.map((set) => ({
    href: yoonSetHref(set.slug), id: `yoon:${set.id}`, imageUrl: set.imageUrl, kind: "set" as const,
    meta: `${YOON_COLLECTION_NAME} - private`, name: set.title, slug: set.slug,
  }))];
}
