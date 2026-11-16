import Link from "next/link";
import { buildArtistHref } from "@/components/archive/archive-hrefs";

type Crumb = { href: string; label: string };

/**
 * Builds the "where this set lives" links for a set page: the private
 * collection for recorded sets, otherwise each linked artist (b2b sets
 * list every artist that has a page).
 */
export const buildSetParentCrumbs = ({
  artists,
  collection,
}: {
  artists: { name: string; slug: string | null }[];
  collection?: Crumb | null;
}): Crumb[] => {
  if (collection) return [collection];
  return artists
    .filter((artist): artist is { name: string; slug: string } => Boolean(artist.slug))
    .map((artist) => ({ href: buildArtistHref({ slug: artist.slug }), label: artist.name }));
};

export function SetBreadcrumb({ parents }: { parents: Crumb[] }) {
  return (
    <nav aria-label="Breadcrumb" className="kicker set-breadcrumb">
      <Link className="set-breadcrumb-root" href="/">Archive</Link>
      <span aria-hidden="true" className="set-breadcrumb-sep set-breadcrumb-root-sep">/</span>
      {parents.length > 0 ? (
        <>
          <span className="set-breadcrumb-parents">
            {parents.map((parent, index) => (
              <span key={parent.href}>
                {index > 0 ? <span aria-hidden="true" className="set-breadcrumb-amp"> &amp; </span> : null}
                <Link className="set-breadcrumb-parent" href={parent.href}>{parent.label}</Link>
              </span>
            ))}
          </span>
          <span aria-hidden="true" className="set-breadcrumb-sep">/</span>
        </>
      ) : null}
      <span aria-current="page" className="set-breadcrumb-current">Set Intelligence Deck</span>
    </nav>
  );
}
