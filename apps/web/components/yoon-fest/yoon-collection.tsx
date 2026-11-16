"use client";
import { ArchiveArtistExplorer, type ArtistExplorerCollection } from "@/components/archive/archive-artist-explorer";
import type { ArchiveArtistSummary } from "@/lib/archive/types";
import { YOON_COLLECTION_HREF, yoonSetHref } from "@/lib/yoon-fest/collection-summary";

const collection: ArtistExplorerCollection = {
  kicker: "Festival Intelligence Deck",
  setHref: yoonSetHref,
  navLinks: [{ label: "Yoon Fest", href: YOON_COLLECTION_HREF }],
  spotifyExport: { entityType: "festival", slug: "yoon-fest", endpoint: "/api/yoon-fest/spotify/export", label: "Export Festival to Spotify" },
};

const management = {
  artistWillBeRemoved: false, canDeleteArtist: false, deletableSetIds: [], deleteImpact: null,
  setDeleteImpacts: {}, submittedByViewer: false, submittedSetIds: [],
};

// The festival uses the artist page layout: hero, recurring tracks, set atlas
// and set explorer. Every link stays inside the private collection.
export function YoonCollection({ summary }: { summary: ArchiveArtistSummary }) {
  return <ArchiveArtistExplorer artist={summary} initialQuery="" management={management} scope="global" collection={collection} />;
}
