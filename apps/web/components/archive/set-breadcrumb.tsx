import Link from "next/link";
import { buildArtistHref } from "@/components/archive/archive-hrefs";
import styles from "./set-breadcrumb.module.css";

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

/**
 * Plain gray "Archive / … / current" trail used as the page kicker.
 * The Archive root links home; parents link up one level.
 */
export function ArchiveBreadcrumb({
  current,
  hideRootOnPhone = false,
  parents = [],
}: {
  current: string;
  hideRootOnPhone?: boolean;
  parents?: Crumb[];
}) {
  const rootClass = hideRootOnPhone ? styles.phoneHidden : undefined;
  return (
    <nav aria-label="Breadcrumb" className={`kicker ${styles.breadcrumb}`}>
      <Link className={rootClass} href="/">Archive</Link>
      <span aria-hidden="true" className={[styles.sep, rootClass].filter(Boolean).join(" ")}>/</span>
      {parents.length > 0 ? (
        <>
          <span>
            {parents.map((parent, index) => (
              <span key={parent.href}>
                {index > 0 ? <span aria-hidden="true" className={styles.sep}> &amp; </span> : null}
                <Link href={parent.href}>{parent.label}</Link>
              </span>
            ))}
          </span>
          <span aria-hidden="true" className={styles.sep}>/</span>
        </>
      ) : null}
      <span aria-current="page">{current}</span>
    </nav>
  );
}

export function SetBreadcrumb({ parents }: { parents: Crumb[] }) {
  return <ArchiveBreadcrumb current="Set Intelligence Deck" hideRootOnPhone parents={parents} />;
}
