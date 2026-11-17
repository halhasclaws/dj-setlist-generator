import { ArchiveArtistExplorer } from "@/components/archive/archive-artist-explorer";
import { ArchiveSetExplorer } from "@/components/archive/archive-set-explorer";
import type {
  ArchiveArtistManagement,
  ArchiveSetManagement,
} from "@/lib/archive/deletions";
import type {
  ArchiveArtistSummary,
  ArchiveSetDetail,
} from "@/lib/archive/types";

export function ArchiveArtistPage({
  artist,
  management,
  query,
  scope,
}: {
  artist: ArchiveArtistSummary;
  management: ArchiveArtistManagement;
  query: string;
  scope: "global" | "mine";
}) {
  return <ArchiveArtistExplorer artist={artist} initialQuery={query} management={management} scope={scope} />;
}

export function ArchiveSetPage({
  detail,
  initialLiked,
  initialListened,
  management,
  query,
}: {
  detail: ArchiveSetDetail;
  initialLiked: boolean | null;
  initialListened: boolean | null;
  management: ArchiveSetManagement;
  query: string;
}) {
  return <ArchiveSetExplorer detail={detail} initialLiked={initialLiked} initialListened={initialListened} initialQuery={query} management={management} />;
}
