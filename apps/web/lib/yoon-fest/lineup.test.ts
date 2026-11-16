import { describe, expect, it } from "vitest";
import { lineupTitle, sortByLineup } from "./lineup";

describe("Yoon lineup titles", () => {
  it("uses the lineup name with day and time", () => {
    expect(lineupTitle("yoon-fest-jackson-sunday-pilot")).toBe("Jackson Algeo (Sun. 3:30 - 5:30 PM)");
    expect(lineupTitle("yoon-fest-choice-friday-mean-gaps-v2")).toBe("Choice (Fri. 10:00 PM - 12:00 AM)");
    expect(lineupTitle("yoon-fest-pily-saturday-mean-gaps-v2")).toBe("Pily (Sat. 12:30 - 2:00 PM)");
    expect(lineupTitle("yoon-fest-hank-friday-mean-gaps-v2")).toBe("Hank (Fri. 12:00 - 1:30 AM)");
  });
  it("leaves unknown slugs alone", () => expect(lineupTitle("synthetic-set")).toBeNull());
});

describe("Yoon lineup order", () => {
  it("sorts by the lineup with Krane before Donald and unknown sets last", () => {
    const slugs = ["synthetic-set", "yoon-fest-donald-saturday-night", "yoon-fest-jackson-sunday-pilot", "yoon-fest-krane-saturday", "yoon-fest-tompson-jake-cattani-partial"];
    expect(sortByLineup(slugs.map((slug) => ({ slug }))).map((item) => item.slug)).toEqual([
      "yoon-fest-tompson-jake-cattani-partial", "yoon-fest-krane-saturday", "yoon-fest-donald-saturday-night",
      "yoon-fest-jackson-sunday-pilot", "synthetic-set",
    ]);
  });
});
