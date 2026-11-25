import { describe, expect, it } from "vitest";
import { matchYoonSearch, normalizeSearchText, type YoonSearchName } from "./search";

const names: YoonSearchName[] = [
  { id: "a", slug: "yoon-fest-jackson-sunday-pilot", title: "Jackson Algeo (Sun. 3:30 - 5:30 PM)", performer: "Jackson Algeo", imageUrl: null },
  { id: "b", slug: "yoon-fest-honeydu-saturday-mean-gaps-v2", title: "Honeydü (Sat. 4:30 - 6:00 AM)", performer: "Honeydü", imageUrl: "https://i.scdn.co/image/x" },
  { id: "c", slug: "yoon-fest-adam-rose-miro-saturday", title: "Adam Rose & Miro (Sat. 9:00 - 11:00 PM)", performer: null, imageUrl: null },
];
const ids = (query: string) => matchYoonSearch(query, names).map((result) => result.id);

describe("private collection search matching", () => {
  it("offers the collection first, then every set in lineup order, for Yoon", () => {
    for (const query of ["yoon", "Yoon", "yo", "yoon fest", "Yoon Fest", "yoonfest", "fest"]) {
      expect(ids(query)).toEqual(["yoon-fest", "yoon:b", "yoon:c", "yoon:a"]);
    }
    const [collection, set] = matchYoonSearch("yoon", names);
    expect(collection).toMatchObject({ kind: "collection", href: "/collections/yoon-fest", name: "Yoon Fest", meta: "Private collection - 3 sets" });
    expect(set).toMatchObject({ kind: "set", href: "/collections/yoon-fest/sets/yoon-fest-honeydu-saturday-mean-gaps-v2", name: "Honeydü (Sat. 4:30 - 6:00 AM)" });
  });
  it("narrows sets by name, with or without collection words", () => {
    expect(ids("yoon jackson")).toEqual(["yoon-fest", "yoon:a"]);
    expect(ids("jackson")).toEqual(["yoon-fest", "yoon:a"]);
    expect(ids("adam rose")).toEqual(["yoon-fest", "yoon:c"]);
    expect(ids("honeydu")).toEqual(["yoon-fest", "yoon:b"]);
  });
  it("returns nothing for unrelated or too-short queries", () => {
    expect(ids("villalobos")).toEqual([]);
    expect(ids("y")).toEqual([]);
    expect(ids("  ")).toEqual([]);
    expect(ids("fe")).toEqual([]);
    expect(ids("yoon villalobos")).toEqual(["yoon-fest"]);
  });
  it("normalizes accents and punctuation", () => {
    expect(normalizeSearchText("Sinéad & Honeydü!")).toBe("sinead honeydu");
  });
});
