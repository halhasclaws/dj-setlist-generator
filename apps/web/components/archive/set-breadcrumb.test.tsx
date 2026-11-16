import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ArchiveBreadcrumb, SetBreadcrumb, buildSetParentCrumbs } from "./set-breadcrumb";

describe("set breadcrumb", () => {
  it("links a public set back to its artist page", () => {
    const parents = buildSetParentCrumbs({ artists: [{ name: "Fred Everything", slug: "fred-everything" }] });
    const html = renderToStaticMarkup(<SetBreadcrumb parents={parents} />);
    expect(html).toContain('href="/artists/fred-everything"');
    expect(html).toContain(">Fred Everything</a>");
    expect(html).toContain('href="/"');
    expect(html).toContain("Set Intelligence Deck");
  });

  it("lists every artist of a b2b set", () => {
    const parents = buildSetParentCrumbs({ artists: [
      { name: "Floating Points", slug: "floating-points" },
      { name: "Four Tet", slug: "four-tet" },
    ] });
    expect(parents.map((parent) => parent.href)).toEqual(["/artists/floating-points", "/artists/four-tet"]);
  });

  it("links a private recording to its collection, never to a public artist page", () => {
    const parents = buildSetParentCrumbs({
      artists: [{ name: "Someone", slug: "someone" }],
      collection: { href: "/collections/yoon-fest", label: "Yoon Fest" },
    });
    const html = renderToStaticMarkup(<SetBreadcrumb parents={parents} />);
    expect(html).toContain('href="/collections/yoon-fest"');
    expect(html).not.toContain("/artists/");
  });

  it("falls back to the plain label when no artist page exists", () => {
    const html = renderToStaticMarkup(<SetBreadcrumb parents={buildSetParentCrumbs({ artists: [] })} />);
    expect(html).not.toContain("/artists/");
    expect(html).toContain("Set Intelligence Deck");
  });
});

describe("artist page breadcrumb", () => {
  it("shows Archive / artist with Archive linking home", () => {
    const html = renderToStaticMarkup(<ArchiveBreadcrumb current="Fred Everything" />);
    expect(html).toMatch(/<a[^>]*href="\/"[^>]*>Archive<\/a>/);
    expect(html).toContain('aria-current="page">Fred Everything</span>');
    expect(html).not.toContain("Intelligence Deck");
  });
});
