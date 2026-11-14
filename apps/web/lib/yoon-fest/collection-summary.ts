import type {
  ArchiveArtistAtlasTrack, ArchiveArtistSet, ArchiveArtistSummary, ArchiveConfidence, ArchiveRecurringTrack,
  ArchiveSetDetail,
} from "@/lib/archive/types";
import { pickFirstImageUrl } from "@/lib/archive/artist-visuals";
import { buildTrackKey, formatCompactDuration } from "@/lib/archive/utils";

export const YOON_COLLECTION_HREF = "/collections/yoon-fest";
export const yoonSetHref = (slug: string) => `${YOON_COLLECTION_HREF}/sets/${slug}`;

const emptyCounts = (): Record<ArchiveConfidence, number> => ({ HIGH: 0, MEDIUM: 0, LOW: 0, UNCERTAIN: 0 });
const isUnknown = (title: string) => title === "Unknown Track";
const setImage = (detail: ArchiveSetDetail) => pickFirstImageUrl([
  detail.heroImageUrl, detail.thumbnailUrl, ...detail.tracks.map((track) => track.albumArt),
]);

/** Present the private collection with the same shape as an artist summary,
 * so it renders in the artist explorer. Links stay inside the collection. */
export function buildYoonCollectionSummary(details: ArchiveSetDetail[]): ArchiveArtistSummary {
  const recurring = new Map<string, Omit<ArchiveRecurringTrack, "genres"> & { genres: Set<string> }>();
  const atlasTracks: ArchiveArtistAtlasTrack[] = [];
  const genres = new Map<string, number>();
  const labels = new Map<string, number>();
  let detections = 0;

  for (const detail of details) {
    for (const track of detail.tracks) {
      if (isUnknown(track.title)) continue;
      detections += 1;
      for (const genre of track.genres) genres.set(genre, (genres.get(genre) ?? 0) + 1);
      if (track.label) labels.set(track.label, (labels.get(track.label) ?? 0) + 1);
      const trackKey = buildTrackKey(track.artist, track.title);
      const href = `${yoonSetHref(detail.slug)}#track-${track.idx}`;
      const entry = recurring.get(trackKey) ?? {
        trackKey, artist: track.artist, title: track.title, appearances: 0, confidenceCounts: emptyCounts(),
        albumArt: track.albumArt, spotifyUrl: track.spotifyUrl, genres: new Set<string>(), label: track.label, setRefs: [],
      };
      entry.appearances += 1;
      entry.confidenceCounts[track.conf] += 1;
      entry.albumArt ??= track.albumArt;
      entry.spotifyUrl ??= track.spotifyUrl;
      entry.label ??= track.label;
      for (const genre of track.genres) entry.genres.add(genre);
      entry.setRefs.push({ setTitle: detail.title, href, confidence: track.conf, position: track.idx });
      recurring.set(trackKey, entry);
      atlasTracks.push({
        idx: track.idx, trackKey, artist: track.artist, title: track.title, confidence: track.conf, time: track.startFmt,
        genres: track.genres, label: track.label, labelUrl: track.labelUrl, spotifyUrl: track.spotifyUrl,
        youtubeUrl: track.youtubeUrl, discogsUrl: track.discogsUrl, albumArt: track.albumArt, setId: detail.id,
        setSlug: detail.slug, setHref: href, sourceDeepLink: null,
        timeRange: track.endFmt ? `${track.startFmt} - ${track.endFmt}` : track.startFmt, setTitle: detail.title,
      });
    }
  }

  const sets: ArchiveArtistSet[] = details.map((detail) => {
    const confidenceCounts = emptyCounts();
    for (const track of detail.tracks) confidenceCounts[track.conf] += 1;
    return {
      id: detail.id, slug: detail.slug, title: detail.title, listenProgress: null, sourceUrl: null,
      thumbnailUrl: setImage(detail), duration: detail.duration, durationFmt: formatCompactDuration(detail.duration),
      totalTracks: detail.tracks.length, recognizedTracks: detail.tracks.filter((track) => !isUnknown(track.title)).length,
      recognitionRate: detail.recognitionRate, confidenceCounts,
      trackSearchText: detail.tracks.map((track) => `${track.artist} ${track.title}`).join(" ").trim(),
      tracks: detail.tracks.map((track) => ({
        end: track.end, endTimeFormatted: track.endFmt, isUnknown: isUnknown(track.title), position: track.idx,
        artist: track.artist, start: track.start, title: track.title, startTimeFormatted: track.startFmt,
        confidence: track.conf, spotifyUrl: track.spotifyUrl, trackHref: `${yoonSetHref(detail.slug)}#track-${track.idx}`,
        trackKey: buildTrackKey(track.artist, track.title),
      })),
    };
  });

  const recurringTracks = [...recurring.values()]
    .map<ArchiveRecurringTrack>((entry) => ({ ...entry, genres: [...entry.genres] }))
    .sort((left, right) => right.appearances - left.appearances || left.title.localeCompare(right.title));

  return {
    id: "yoon-fest", slug: "yoon-fest", name: "Yoon Fest", imageUrl: null,
    heroImageUrl: pickFirstImageUrl(details.map(setImage)),
    generatedAt: details.map((detail) => detail.generatedAt).filter(Boolean).sort().at(-1) ?? null,
    stats: {
      setsAnalyzed: details.length, uniqueTracks: recurring.size, totalDetections: detections,
      recurringTracks: recurringTracks.filter((track) => track.appearances > 1).length,
    },
    topGenres: [...genres.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6).map(([name]) => name),
    topLabels: [...labels.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8).map(([name, count]) => ({ name, count })),
    recurringTracks, sets, atlasTracks, failedSets: [],
  };
}
