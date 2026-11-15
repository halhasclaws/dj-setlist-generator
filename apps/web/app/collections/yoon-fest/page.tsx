import type { Metadata } from "next";
import { YoonCollection } from "@/components/yoon-fest/yoon-collection";
import { YoonAccessBoundary } from "@/components/yoon-fest/yoon-access-boundary";
import { requireYoonPageActor } from "@/lib/yoon-fest/page-access.server";
import { getYoonSets, toYoonSetDetail } from "@/lib/yoon-fest/data.server";
import { buildYoonCollectionSummary } from "@/lib/yoon-fest/collection-summary";
import { sortByLineup } from "@/lib/yoon-fest/lineup";
export const dynamic = "force-dynamic";
export const revalidate = 0;
// Generic even for authorized users: no private title in previews/metadata.
export const metadata: Metadata = { title: "Private collection", robots: { index: false, follow: false, noarchive: true }, referrer: "no-referrer" };
export default async function YoonCollectionPage() {
  const actor = await requireYoonPageActor();
  const summary = buildYoonCollectionSummary(sortByLineup(await getYoonSets(actor)).map(toYoonSetDetail));
  return <YoonAccessBoundary viewerId={actor.userId}><YoonCollection summary={summary} /></YoonAccessBoundary>;
}
