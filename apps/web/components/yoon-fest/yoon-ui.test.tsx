import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ArchiveSetExplorer } from "@/components/archive/archive-set-explorer";
import { YoonCollection } from "./yoon-collection";
import { toYoonSetDetail } from "@/lib/yoon-fest/data.server";
import { fixture } from "@/lib/yoon-fest/fixtures.test-support";
import { buildYoonCollectionSummary } from "@/lib/yoon-fest/collection-summary";
vi.mock("@/components/archive/archive-header", () => ({ ArchiveHeader: () => <header>Archive</header> }));
vi.mock("@/components/archive/use-spotify-export-status", () => ({ useSpotifyExportStatus: () => ({ isAuthenticated: true, isLoading: false, spotifyConfigured: true, spotifyConnected: true }) }));
const set = fixture.sets[0]!; const detail = toYoonSetDetail(set);
describe("private archive UI reuse", () => {
  it("renders real audio, original track timeline and export notice without public source/provenance", () => {
    const html = renderToStaticMarkup(<ArchiveSetExplorer detail={detail} initialListened={null} initialQuery="" management={{ canDeleteSet: false, deleteImpact: null, setWillBeRemoved: false, submittedByViewer: false }} privateContext={{ collectionHref: "/collections/yoon-fest", boundaryNote: set.boundaryNote, audio: { src: `/api/yoon-fest/media/${set.audio.assetId}`, revision: set.audio.revision } }} />);
    expect(html).toContain("<audio");
    expect(html.match(/<audio[^>]*>/)?.[0]).not.toMatch(/\scontrols(?:=|\s|>)/);
    expect(html.match(/<audio[^>]*>/)?.[0]).toMatch(/playsinline/i);
    expect(html).toContain('aria-label="Set playback"');
    expect(html).toContain('aria-label="Seek within set"'); expect(html).toMatch(/controlslist="nodownload"/i); expect(html).not.toContain("download="); expect(html).toContain(`/api/yoon-fest/media/${set.audio.assetId}`); expect(html).toContain('id="track-2"'); expect(html).toContain("may be accessible by link");
    expect(html).not.toContain("Embedded playback is unavailable"); expect(html).not.toContain("Open Source"); expect(html).not.toContain("startSample"); expect(html).not.toContain("synthetic-a"); expect(html).not.toContain("rlkey"); expect(html).not.toContain("dropbox.com"); expect(html).not.toContain("Anyone who receives an audio link"); expect(html).not.toContain(set.boundaryNote); expect(html).toContain("Set Intelligence Deck");
  });
  it("renders the festival like an artist page with links only to the private set route", () => {
    const html = renderToStaticMarkup(<YoonCollection summary={buildYoonCollectionSummary([detail])} />);
    expect(html).toContain("Festival Intelligence Deck"); expect(html).toContain("Set Atlas"); expect(html).toContain("Set Explorer");
    expect(html).toContain("/collections/yoon-fest/sets/synthetic-set"); expect(html).toContain("Export Festival to Spotify");
    expect(html).not.toContain('href="/sets/synthetic-set'); expect(html).not.toContain("Collection Status");
    expect(html).not.toContain("dropbox.com"); expect(html).not.toContain(set.boundaryNote);
  });
});
