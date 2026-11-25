"""Build setlist from recognition results with advanced clustering."""

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Optional

from config import Config
from detail_explorer_common import UNKNOWN_ARTIST, UNKNOWN_TITLE
from false_positive_policy import get_policy
from false_positive_score import entry_features, score as false_positive_score

CONFIDENCE_ICONS = {
    'HIGH': '🟢',
    'MEDIUM': '🟡',
    'LOW': '🟠',
    'UNCERTAIN': '⚪',
}

TRACK_ID_SEPARATOR = '|'


def clustering_timing_tag() -> str:
    """Short tag for the clustering timing rule in force (recorded on each publish)."""
    if Config.OFFSET_AGREEMENT_MIN > 0 and Config.OFFSET_TIMING_EXTEND_WINDOWS > 0:
        return f"d07b_{Config.OFFSET_TIMING_EXTEND_MODE}{Config.OFFSET_TIMING_EXTEND_WINDOWS}"
    return "d07" if Config.OFFSET_AGREEMENT_MIN > 0 else "legacy"


def make_track_id(artist: str, title: str, shazam_id: Optional[str]) -> str:
    """Build a track_id string from its components."""
    return f"{artist}{TRACK_ID_SEPARATOR}{title}{TRACK_ID_SEPARATOR}{shazam_id}"


def parse_track_id(track_id: str) -> tuple[str, str, str]:
    """Parse a track_id string into (artist, title, shazam_id)."""
    parts = track_id.split(TRACK_ID_SEPARATOR)
    return parts[0], parts[1], parts[2]


@dataclass
class Track:
    """Represents a track in the setlist."""
    title: str
    artist: str
    start_time: float
    end_time: Optional[float]
    confidence: str
    detection_count: int
    shazam_track_id: Optional[str]
    isrc: Optional[str]
    cluster_density: float
    cluster_span: int
    segment_indices: List[int]


@dataclass
class SuppressedFalsePositive:
    """Diagnostic details for a cluster removed by policy."""

    artist: str
    title: str
    shazam_track_id: Optional[str]
    detection_count: int
    cluster_density: float
    cluster_span: int
    start_segment: int
    end_segment: int
    match_type: str
    rule_id: str
    rule_reason: str


class SetlistBuilder:
    """Build deduplicated setlist from recognitions."""

    def __init__(self):
        self._false_positive_policy = get_policy()
        self._last_suppressed_false_positives: list[SuppressedFalsePositive] = []

    def build_setlist(self, recognitions: list) -> list[Track]:
        """Build setlist from recognition results."""
        self._last_suppressed_false_positives = []
        valid_recognitions = [r for r in recognitions if r.recognized]

        if not valid_recognitions:
            print("No tracks recognized")
            return []

        # Step 1: Create clusters (group all detections by track_id)
        clusters = self._create_clusters(valid_recognitions)

        # Step 2: Suppress known false positives before overlap resolution.
        clusters = self._suppress_false_positive_clusters(clusters)

        # Step 2b: A sample wrapped around its host track yields to it (D07c).
        if Config.SAMPLE_YIELD_MAX_AGREEING > 0:
            clusters = self._yield_wrapped_samples(clusters)
        if Config.LOOP_RESCUE_RUN > 0:
            clusters = self._drop_contested_rescues(clusters)

        # Step 3: Resolve temporal overlaps (competing tracks at same time)
        # Do this BEFORE filtering to choose dominant track among competitors
        if Config.OVERLAP_RESOLUTION_ENABLED:
            clusters = self._resolve_overlapping_clusters(clusters)

        # Log cluster details for diagnostics
        self._log_clusters(clusters)

        # Convert to tracks
        tracks = [self._cluster_to_track(cluster) for cluster in clusters]

        # Collapse duplicate versions of one track (D07)
        if Config.DUPLICATE_MERGE_SECONDS > 0:
            tracks = self._merge_duplicate_versions(tracks)

        # Drop entries the combined false-positive score rates unlikely (D07)
        if Config.FALSE_POSITIVE_SCORE_MIN > 0:
            tracks = self._apply_false_positive_score(tracks, valid_recognitions)

        # Calculate confidence
        tracks = self._calculate_confidence(tracks)

        print(f"\n{'='*70}")
        print(f"CLUSTERING RESULTS")
        print(f"{'='*70}")
        print(f"Built setlist with {len(tracks)} tracks")

        return tracks
    
    def _create_clusters(self, recognitions: list) -> list[dict]:
        """Group ALL detections by track_id (simplified approach - no gap splitting).

        This simplified algorithm groups all detections of the same track together,
        regardless of gap size. Overlap resolution will handle competing detections.
        """
        if not recognitions:
            return []

        print(f"\n{'='*70}")
        print(f"CLUSTERING PHASE (Simplified)")
        print(f"{'='*70}")

        sorted_recs = sorted(recognitions, key=lambda x: x.segment_index)

        # Group by track ID - collect ALL detections for each track
        track_sequences = defaultdict(list)
        for rec in sorted_recs:
            track_id = make_track_id(rec.artist, rec.track_title, rec.shazam_track_id)
            track_sequences[track_id].append(rec)

        clusters = []

        # Create one cluster per track_id (all detections grouped together)
        for track_id, recs in track_sequences.items():
            artist, title, _ = parse_track_id(track_id)

            all_recs = recs
            loop_rescued = False
            if Config.OFFSET_AGREEMENT_MIN > 0:
                agreeing = self._offset_agreeing(recs)
                if len(agreeing) < Config.OFFSET_AGREEMENT_MIN:
                    rescued = self._loop_rescue(recs)
                    if not rescued:
                        print(f"✗ Skipped: {artist} - {title} ({len(agreeing)} offset-agreeing detections "
                              f"< {Config.OFFSET_AGREEMENT_MIN} min)")
                        continue
                    print(f"↺ Loop rescue: {artist} - {title} ({len(rescued)} consecutive windows)")
                    agreeing = rescued
                    loop_rescued = True
                timing = self._extend_agreeing(recs, agreeing)
                recs = agreeing
                if Config.OFFSET_TIMING_EXTEND_MODE == 'cluster':
                    recs = timing
            else:
                timing = None

            # Only create cluster if we have minimum detections and density
            cluster = self._make_cluster_dict(track_id, recs)
            if timing is not None and timing is not recs:
                cluster['timing_recognitions'] = timing
            cluster['all_recognitions'] = all_recs
            if loop_rescued:
                cluster['loop_rescued'] = True
            density = cluster['density']

            if len(recs) < Config.MIN_CLUSTER_SIZE:
                print(f"✗ Skipped: {artist} - {title} ({len(recs)} detections < {Config.MIN_CLUSTER_SIZE} min)")
            elif density < Config.MIN_CLUSTER_DENSITY:
                print(f"✗ Skipped: {artist} - {title} (density {density:.2f} < {Config.MIN_CLUSTER_DENSITY} min)")
            else:
                clusters.append(cluster)
                print(f"✓ Clustered: {artist} - {title} ({len(recs)} detections, density {density:.2f})")

        clusters.sort(key=lambda c: c['start_segment'])
        print(f"\nCreated {len(clusters)} initial clusters")
        return clusters
    
    @staticmethod
    def _match_offset(rec) -> Optional[float]:
        """Provider offset of the matched audio within the track, in seconds."""
        matches = (rec.raw_data or {}).get('matches') if isinstance(rec.raw_data, dict) else None
        if not isinstance(matches, list) or not matches or not isinstance(matches[0], dict):
            return None
        offset = matches[0].get('offset')
        return float(offset) if type(offset) in (int, float) else None

    def _offset_agreeing(self, recognitions: list) -> list:
        """Largest group of detections from one continuous playback.

        While a track plays, set time minus the provider's track offset stays
        constant, so detections of the same playback share an anchor. Take the
        largest group whose anchors lie within OFFSET_AGREEMENT_SECONDS of one
        detection's anchor (earliest such group on ties). A median would fall
        between two equal groups, e.g. a looped section.
        """
        anchored = [(rec.timestamp - offset, rec) for rec in recognitions
                    if (offset := self._match_offset(rec)) is not None]
        best: list = []
        for anchor, _ in anchored:
            group = [rec for other, rec in anchored
                     if abs(other - anchor) <= Config.OFFSET_AGREEMENT_SECONDS]
            if len(group) > len(best):
                best = group
        return best

    @staticmethod
    def _extend_agreeing(recognitions: list, agreeing: list) -> list:
        """The agreeing group plus every detection of the same track that connects
        to it through gaps of at most OFFSET_TIMING_EXTEND_WINDOWS windows (D07b)."""
        gap = Config.OFFSET_TIMING_EXTEND_WINDOWS
        if gap <= 0 or not agreeing:
            return agreeing
        lo = min(r.segment_index for r in agreeing)
        hi = max(r.segment_index for r in agreeing)
        indices = sorted({r.segment_index for r in recognitions})
        for i in reversed([i for i in indices if i < lo]):
            if lo - i > gap:
                break
            lo = i
        for i in [i for i in indices if i > hi]:
            if i - hi > gap:
                break
            hi = i
        return sorted((r for r in recognitions if lo <= r.segment_index <= hi), key=lambda r: r.segment_index)

    def _loop_rescue(self, recognitions: list) -> list:
        """Longest run of consecutive windows for a track that fails offset agreement,
        when it looks like a looped section rather than one fragment matched over and
        over (D07c). Empty when the rule is off or nothing qualifies."""
        need = Config.LOOP_RESCUE_RUN
        if need <= 0:
            return []
        recs = sorted(recognitions, key=lambda r: r.segment_index)
        runs, run = [], []
        for r in recs:
            if run and r.segment_index != run[-1].segment_index + 1:
                runs.append(run)
                run = []
            run.append(r)
        runs.append(run)
        best = max(runs, key=len)
        if len(best) < need:
            return []
        offsets = [self._match_offset(r) for r in best]
        if any(o is None for o in offsets):
            return []
        if any(abs(b - a) < Config.LOOP_RESCUE_FROZEN_SECONDS for a, b in zip(offsets, offsets[1:])):
            return []
        fskews = [abs(v) for r in best if type(v := (((r.raw_data or {}).get('matches') or [{}])[0] or {})
                                                   .get('frequencyskew')) in (int, float)]
        if fskews and max(fskews) >= Config.LOOP_RESCUE_MAX_FSKEW:
            return []
        return best

    def _drop_contested_rescues(self, clusters: list[dict]) -> list[dict]:
        """A loop-rescued cluster only fills a gap: drop it if its run overlaps
        any offset-agreeing cluster, so it never displaces a verified track (D07c)."""
        def span(c, timed=False):
            recs = (c.get('timing_recognitions') or c['recognitions']) if timed else c['recognitions']
            idx = [r.segment_index for r in recs]
            return min(idx), max(idx)

        # Compare against each verified track's full timed span (D07b), so a
        # rescue can't land in the middle of a track that is already listed.
        agreeing = [span(c, timed=True) for c in clusters if not c.get('loop_rescued')]
        kept = []
        for c in clusters:
            if c.get('loop_rescued'):
                a0, a1 = span(c)
                if any(a0 <= b1 and b0 <= a1 for b0, b1 in agreeing):
                    print(f"  ✗ Rescue contested: {c['artist']} - {c['title']}")
                    continue
            kept.append(c)
        return kept

    def _yield_wrapped_samples(self, clusters: list[dict]) -> list[dict]:
        """Drop a weakly agreeing cluster whose detections wrap around another
        cluster's agreeing group; the host takes over its time span (D07c)."""
        gap = max(Config.OFFSET_TIMING_EXTEND_WINDOWS, 1)

        def ratio(c):
            with_offset = [r for r in c.get('all_recognitions', c['recognitions'])
                           if self._match_offset(r) is not None]
            return len(c['recognitions']) / len(with_offset) if with_offset else 0.0

        def base(c):
            return (self._base_key(c['artist']), self._base_key(c['title']))

        dropped = set()
        for s_idx, sample in enumerate(clusters):
            if (sample['detection_count'] > Config.SAMPLE_YIELD_MAX_AGREEING
                    or ratio(sample) > Config.SAMPLE_YIELD_SAMPLE_RATIO):
                continue
            s_timing = sample.get('timing_recognitions') or sample['recognitions']
            s0 = min(r.segment_index for r in s_timing)
            s1 = max(r.segment_index for r in s_timing)
            for h_idx, host in enumerate(clusters):
                if h_idx == s_idx or h_idx in dropped or base(host) == base(sample):
                    continue
                if ratio(host) < Config.SAMPLE_YIELD_HOST_RATIO:
                    continue
                # The sample's timed span must start just before and end just
                # after the host's agreeing group (within `gap` windows each
                # side), i.e. it tightly wraps the host. Stray detections far
                # away never count, so a host can't be stretched across a set.
                h0 = min(r.segment_index for r in host['recognitions'])
                h1 = max(r.segment_index for r in host['recognitions'])
                if not (h0 - gap <= s0 < h0 and h1 < s1 <= h1 + gap):
                    continue
                timed = (host.get('timing_recognitions') or host['recognitions']) + \
                        (sample.get('timing_recognitions') or sample['recognitions'])
                host['timing_recognitions'] = sorted(timed, key=lambda r: r.segment_index)
                dropped.add(s_idx)
                print(f"  ⤵ SAMPLE YIELD: {sample['artist']} - {sample['title']} "
                      f"inside {host['artist']} - {host['title']}")
                break
        return [c for i, c in enumerate(clusters) if i not in dropped]

    def _make_cluster_dict(self, track_id: str, recognitions: list) -> dict:
        """Create cluster dictionary from recognitions."""
        artist, title, shazam_id = parse_track_id(track_id)
        shazam_track_id = None if shazam_id in {"", "None"} else shazam_id
        segment_indices = [r.segment_index for r in recognitions]
        start_seg = min(segment_indices)
        end_seg = max(segment_indices)
        span = end_seg - start_seg + 1
        count = len(recognitions)
        density = count / span

        isrc = next(
            (r.raw_data['track']['isrc'] for r in recognitions
             if r.raw_data and r.raw_data.get('track', {}).get('isrc')),
            None
        )

        return {
            'track_id': track_id,
            'artist': artist,
            'title': title,
            'shazam_track_id': shazam_track_id,
            'isrc': isrc,
            'recognitions': recognitions,
            'segment_indices': segment_indices,
            'start_segment': start_seg,
            'end_segment': end_seg,
            'span': span,
            'detection_count': count,
            'density': density
        }

    def _suppress_false_positive_clusters(self, clusters: list[dict]) -> list[dict]:
        """Remove clusters that match the known false-positive policy."""
        if not clusters or not self._false_positive_policy.rules:
            return clusters

        print(f"\n{'='*70}")
        print("FALSE-POSITIVE SUPPRESSION PHASE")
        print(f"{'='*70}")

        kept_clusters = []
        for cluster in clusters:
            match = self._false_positive_policy.match(
                cluster['artist'],
                cluster['title'],
                cluster['shazam_track_id'],
            )
            if not match:
                kept_clusters.append(cluster)
                continue

            diagnostic = SuppressedFalsePositive(
                artist=cluster['artist'],
                title=cluster['title'],
                shazam_track_id=cluster['shazam_track_id'],
                detection_count=cluster['detection_count'],
                cluster_density=cluster['density'],
                cluster_span=cluster['span'],
                start_segment=cluster['start_segment'],
                end_segment=cluster['end_segment'],
                match_type=match.match_type,
                rule_id=match.rule.id,
                rule_reason=match.rule.reason,
            )
            self._last_suppressed_false_positives.append(diagnostic)
            print(f"  🚫 SUPPRESSED: {diagnostic.artist} - {diagnostic.title}")
            print(
                f"     └─ match={diagnostic.match_type}, rule={diagnostic.rule_id}, "
                f"detections={diagnostic.detection_count}, density={diagnostic.cluster_density:.2f}"
            )
            print(f"     └─ reason={diagnostic.rule_reason}")

        if not self._last_suppressed_false_positives:
            print("  No clusters matched known false positives")
        else:
            print(
                f"Suppressed {len(self._last_suppressed_false_positives)} known false-positive cluster(s)"
            )

        return kept_clusters

    def _resolve_overlapping_clusters(self, clusters: list[dict]) -> list[dict]:
        """When tracks overlap in time, keep the dominant one using multi-criteria scoring.

        Score formula: detection_count * 10.0 + density * 20.0
        Span is excluded to prevent scattered detections from winning.
        """
        if not clusters:
            return []

        print(f"\n{'='*70}")
        print(f"OVERLAP RESOLUTION PHASE")
        print(f"{'='*70}")

        sorted_clusters = sorted(clusters, key=lambda c: c['start_segment'])
        resolved = []
        i = 0
        overlap_count = 0

        while i < len(sorted_clusters):
            current = sorted_clusters[i]
            overlapping = [current]

            # Find all clusters that overlap with current
            for j in range(i + 1, len(sorted_clusters)):
                next_cluster = sorted_clusters[j]

                # Check if they overlap in time
                if self._clusters_overlap(current, next_cluster):
                    overlapping.append(next_cluster)
                elif next_cluster['start_segment'] > current['end_segment']:
                    # No more overlaps possible
                    break

            if len(overlapping) > 1:
                print(f"\n⚠️  OVERLAP DETECTED: {len(overlapping)} competing tracks")

                # Calculate scores for each track
                # Score formula: prioritize detection count and density, not span
                # Span is excluded because scattered detections shouldn't win
                def calc_score(c):
                    return c['detection_count'] * 10.0 + c['density'] * 20.0

                for c in overlapping:
                    score = calc_score(c)
                    print(f"  📊 {c['artist']} - {c['title']}")
                    print(f"     └─ {c['detection_count']} detections, span {c['span']}, density {c['density']:.2f}")
                    print(f"     └─ Score: {score:.1f}")

                # Choose track with highest score
                winner = max(overlapping, key=calc_score)

                print(f"  ✅ KEEPING: {winner['artist']} - {winner['title']}")

                for c in overlapping:
                    if c != winner:
                        print(f"  ❌ REMOVING: {c['artist']} - {c['title']}")

                resolved.append(winner)
                overlap_count += 1

                # Skip all losing clusters
                i += len(overlapping)
            else:
                resolved.append(current)
                i += 1

        print(f"\nResolved {overlap_count} overlap conflict(s)")
        print(f"Clusters after resolution: {len(resolved)} (from {len(sorted_clusters)})")

        return resolved

    def _clusters_overlap(self, cluster1: dict, cluster2: dict) -> bool:
        """Check if two clusters overlap in time (>= configured threshold overlap)."""
        start1, end1 = cluster1['start_segment'], cluster1['end_segment']
        start2, end2 = cluster2['start_segment'], cluster2['end_segment']

        # Calculate overlap
        overlap_start = max(start1, start2)
        overlap_end = min(end1, end2)
        overlap = max(0, overlap_end - overlap_start)

        # Check if overlap is significant (>= configured threshold, default 30%)
        span1 = end1 - start1
        span2 = end2 - start2

        return overlap >= min(span1, span2) * Config.OVERLAP_THRESHOLD

    def _log_clusters(self, clusters: list[dict]):
        """Log diagnostic details for each cluster."""
        if not clusters:
            return

        print(f"\n{'='*70}")
        print(f"CLUSTER DETAILS")
        print(f"{'='*70}")

        for cluster in clusters:
            count = cluster['detection_count']
            density = cluster['density']
            span = cluster['span']
            print(f"  {cluster['artist']} - {cluster['title']}")
            print(f"  └─ {count} detections, {density:.0%} density, span {span} segments")
    
    @staticmethod
    def _base_key(text: Optional[str]) -> str:
        text = re.sub(r'[\(\[].*?[\)\]]', ' ', (text or '').lower())
        return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())

    def _merge_duplicate_versions(self, tracks: list) -> list:
        """Same artist + same base title within DUPLICATE_MERGE_SECONDS: keep the
        entry with most detections (the later one on a tie)."""
        kept = []
        for track in sorted(tracks, key=lambda t: t.start_time):
            key = (self._base_key(track.artist), self._base_key(track.title))
            twin = next((k for k in kept if key[1]
                         and (self._base_key(k.artist), self._base_key(k.title)) == key
                         and abs(k.start_time - track.start_time) <= Config.DUPLICATE_MERGE_SECONDS), None)
            if twin is None:
                kept.append(track)
            elif track.detection_count >= twin.detection_count:
                kept[kept.index(twin)] = track
        merged = len(tracks) - len(kept)
        if merged:
            print(f"Merged {merged} duplicate version {'entry' if merged == 1 else 'entries'}")
        return sorted(kept, key=lambda t: t.start_time)

    def _apply_false_positive_score(self, tracks: list, recognitions: list) -> list:
        """Keep entries whose combined false-positive score reaches FALSE_POSITIVE_SCORE_MIN."""
        feats = entry_features(tracks, recognitions, float(Config.SEGMENT_DURATION), Config.OFFSET_AGREEMENT_SECONDS)
        kept = []
        for track, f in zip(tracks, feats):
            value = false_positive_score(f)
            if value >= Config.FALSE_POSITIVE_SCORE_MIN:
                kept.append(track)
            else:
                print(f"✗ Score-filtered: {track.artist} - {track.title} (score {value:.2f} "
                      f"< {Config.FALSE_POSITIVE_SCORE_MIN})")
        return kept

    def _cluster_to_track(self, cluster: dict) -> Track:
        """Convert cluster to Track object."""
        timed = cluster.get('timing_recognitions') or cluster['recognitions']
        first = timed[0]
        last = timed[-1]
        
        return Track(
            title=cluster['title'],
            artist=cluster['artist'],
            start_time=first.timestamp,
            end_time=last.timestamp + 30,
            confidence="",
            detection_count=cluster['detection_count'],
            shazam_track_id=cluster['shazam_track_id'],
            isrc=cluster.get('isrc'),
            cluster_density=cluster['density'],
            cluster_span=cluster['span'],
            segment_indices=cluster['segment_indices']
        )
    
    def _calculate_confidence(self, tracks: list[Track]) -> list[Track]:
        """Calculate confidence scores."""
        for track in tracks:
            # Multi-factor confidence
            if track.detection_count >= 15:
                track.confidence = "HIGH"
            elif track.detection_count >= 10 or (track.detection_count >= 8 and track.cluster_density >= 0.7):
                track.confidence = "HIGH"
            elif track.detection_count >= 5 and track.cluster_density >= 0.6:
                track.confidence = "MEDIUM"
            elif track.detection_count >= 3 and track.cluster_density >= 0.75:
                track.confidence = "MEDIUM"
            else:
                track.confidence = "LOW"
        
        return tracks

    @staticmethod
    def _is_unknown_track(track: Track) -> bool:
        """Return True when a track is a generated unknown gap entry."""
        return track.artist == UNKNOWN_ARTIST and track.title == UNKNOWN_TITLE
    
    def add_unknown_tracks(self, tracks: list[Track], recognitions: list) -> list[Track]:
        """Add Unknown Track entries for gaps outside known cluster spans."""
        if not recognitions:
            return []

        recognition_by_segment = {}
        for rec in recognitions:
            recognition_by_segment.setdefault(rec.segment_index, rec)

        all_segments = sorted(recognition_by_segment)

        claimed_segments = set()
        known_ranges = []
        for track in tracks:
            if self._is_unknown_track(track) or not track.segment_indices:
                continue

            start_idx = min(track.segment_indices)
            end_idx = max(track.segment_indices)
            claimed_segments.update(range(start_idx, end_idx + 1))
            known_ranges.append((start_idx, end_idx, track))

        known_ranges.sort(key=lambda item: item[0])
        gap_segments = [seg_idx for seg_idx in all_segments if seg_idx not in claimed_segments]
        
        # Group consecutive gaps
        unknown_gaps = []
        current_gap = []
        
        for seg_idx in gap_segments:
            if not current_gap or seg_idx - current_gap[-1] <= 2:
                current_gap.append(seg_idx)
            else:
                if len(current_gap) >= Config.MIN_UNKNOWN_GAP_SIZE:
                    unknown_gaps.append(current_gap)
                current_gap = [seg_idx]
        
        if len(current_gap) >= Config.MIN_UNKNOWN_GAP_SIZE:
            unknown_gaps.append(current_gap)
        
        # Create Unknown Track entries
        unknown_tracks = []
        for gap in unknown_gaps:
            gap_recs = [recognition_by_segment[seg_idx] for seg_idx in gap if seg_idx in recognition_by_segment]
            if not gap_recs:
                continue

            raw_start = gap_recs[0].timestamp
            raw_end = gap_recs[-1].timestamp + 30
            gap_start_idx = gap[0]
            gap_end_idx = gap[-1]

            prev_track = None
            prev_end_idx = None
            next_track = None

            for start_idx, end_idx, track in known_ranges:
                if end_idx < gap_start_idx:
                    if prev_end_idx is None or end_idx > prev_end_idx:
                        prev_track = track
                        prev_end_idx = end_idx
                    continue
                if start_idx > gap_end_idx:
                    next_track = track
                    break

            start_time = raw_start
            end_time = raw_end

            if prev_track and prev_track.end_time is not None:
                start_time = max(start_time, prev_track.end_time)
            if next_track:
                end_time = min(end_time, next_track.start_time)

            if end_time <= start_time:
                continue

            unknown_tracks.append(Track(
                title=UNKNOWN_TITLE,
                artist=UNKNOWN_ARTIST,
                start_time=start_time,
                end_time=end_time,
                confidence="UNCERTAIN",
                detection_count=0,
                shazam_track_id=None,
                isrc=None,
                cluster_density=0.0,
                cluster_span=len(gap),
                segment_indices=gap
            ))
        
        print(f"\nIdentified {len(unknown_tracks)} unknown track gaps")
        
        # Merge and sort
        return sorted(tracks + unknown_tracks, key=lambda t: t.start_time)
