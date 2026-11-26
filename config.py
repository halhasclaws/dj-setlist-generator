"""Configuration management for the setlist generator."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional in lean test environments
    def load_dotenv():
        return False

# Load environment variables
load_dotenv()

class Config:
    """Application configuration."""
    
    # API Keys
    SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID', '')
    SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET', '')
    SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8888/callback')
    DISCOGS_TOKEN = os.getenv('DISCOGS_TOKEN', '')
    DISCOGS_CONSUMER_KEY = os.getenv('DISCOGS_CONSUMER_KEY', '')
    DISCOGS_CONSUMER_SECRET = os.getenv('DISCOGS_CONSUMER_SECRET', '')
    # DJ Set Discovery Settings
    DISCOVERY_RESULTS_PER_QUERY = int(os.getenv('DISCOVERY_RESULTS_PER_QUERY', '20'))
    MIN_SET_DURATION_MINUTES = int(os.getenv('MIN_SET_DURATION_MINUTES', '20'))
    MAX_SETS_PER_ARTIST = int(os.getenv('MAX_SETS_PER_ARTIST', '0'))  # 0 = no limit
    # Extra name-only SoundCloud searches that look past the first 20 results.
    DISCOVERY_DEEP_SOUNDCLOUD = os.getenv('DISCOVERY_DEEP_SOUNDCLOUD', 'true').lower() == 'true'
    # AI review of discovery candidates: auto = run when the claude CLI is installed, off = never.
    DISCOVERY_AI_REVIEW = os.getenv('DISCOVERY_AI_REVIEW', 'auto').lower()
    
    # Feature Toggles
    ENABLE_SPOTIFY = os.getenv('ENABLE_SPOTIFY', 'true').lower() == 'true'
    ENABLE_YOUTUBE = os.getenv('ENABLE_YOUTUBE', 'true').lower() == 'true'
    ENABLE_DISCOGS = os.getenv('ENABLE_DISCOGS', 'false').lower() == 'true'
    ENABLE_SPOTIFY_PLAYLISTS = os.getenv('ENABLE_SPOTIFY_PLAYLISTS', 'true').lower() == 'true'
    AUTO_CREATE_SPOTIFY_PLAYLIST = os.getenv('AUTO_CREATE_SPOTIFY_PLAYLIST', 'false').lower() == 'true'
    CREATE_SET_PLAYLISTS = os.getenv('CREATE_SET_PLAYLISTS', 'true').lower() == 'true'
    ENABLE_HTML_OUTPUT = os.getenv('ENABLE_HTML_OUTPUT', 'true').lower() == 'true'

    # Notifications (ntfy.sh)
    NTFY_TOPIC = os.getenv('NTFY_TOPIC', '')  # Set to your ntfy topic to enable notifications

    # Recognition Settings
    SEGMENT_DURATION = int(os.getenv('SEGMENT_DURATION', '30'))
    SEGMENT_OVERLAP = int(os.getenv('SEGMENT_OVERLAP', '15'))
    MIN_CONFIDENCE_THRESHOLD = int(os.getenv('MIN_CONFIDENCE_THRESHOLD', '8'))
    
    # Crash Recovery Settings
    ENABLE_CHECKPOINTS = os.getenv('ENABLE_CHECKPOINTS', 'true').lower() == 'true'
    CHECKPOINT_INTERVAL = int(os.getenv('CHECKPOINT_INTERVAL', '10'))
    
    # Shazam Recognition Settings
    RECOGNITION_TIMEOUT = int(os.getenv('RECOGNITION_TIMEOUT', '15'))
    BASE_DELAY = float(os.getenv('BASE_DELAY', '0.3'))  # Delay between requests

    # Retry Settings (for 429 rate limit handling with JitterRetry)
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', '5'))
    MAX_BACKOFF_DELAY = float(os.getenv('MAX_BACKOFF_DELAY', '30.0'))  # Max backoff cap
    JITTER_INTERVAL_SIZE = float(os.getenv('JITTER_INTERVAL_SIZE', '4.0'))  # Random jitter range is (0, size^2)

    # Concurrency Settings
    CONCURRENT_RECOGNITIONS = int(os.getenv('CONCURRENT_RECOGNITIONS', '2'))  # Number of parallel requests
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', '10'))  # Segments per batch for checkpointing
    RECOGNITION_SLOT_COUNT = int(os.getenv('RECOGNITION_SLOT_COUNT', '10'))
    LEASE_SIZE = int(os.getenv('LEASE_SIZE', '10'))
    AUTO_MAX_RECOGNITION_SLOTS = int(os.getenv('AUTO_MAX_RECOGNITION_SLOTS', '12'))
    AUTO_TARGET_SEGMENTS_PER_SLOT = int(os.getenv('AUTO_TARGET_SEGMENTS_PER_SLOT', '20'))
    AUTO_TARGET_LEASES_PER_SLOT = float(os.getenv('AUTO_TARGET_LEASES_PER_SLOT', '2'))
    AUTO_MIN_LEASE_SIZE = int(os.getenv('AUTO_MIN_LEASE_SIZE', '10'))

    # Quota-Aware Throttling Settings
    QUOTA_COOLDOWN_DURATION = int(os.getenv('QUOTA_COOLDOWN_DURATION', '60'))  # Seconds to wait when quota exhausted
    # A shared provider cooldown at most this long is waited out inside the running
    # recognition job; longer ones (or ones past the job deadline) hand off to a continuation.
    IN_JOB_COOLDOWN_MAX_SECONDS = float(os.getenv('IN_JOB_COOLDOWN_MAX_SECONDS', '900'))
    # When false, a 429 cools down only the throttled slot (its own runner/IP) and
    # that window; other slots keep recognizing. Preview tuning flag.
    SHARED_PROVIDER_COOLDOWN = os.getenv('SHARED_PROVIDER_COOLDOWN', 'true').strip().lower() != 'false'

    # Artist image validation settings
    ARTIST_IMAGE_MIN_GENRE_OVERLAP = float(os.getenv('ARTIST_IMAGE_MIN_GENRE_OVERLAP', '0.2'))
    
    # Cleanup Settings
    CLEANUP_TEMP_FILES = os.getenv('CLEANUP_TEMP_FILES', 'true').lower() == 'true'
    CLEANUP_CHECKPOINTS = os.getenv('CLEANUP_CHECKPOINTS', 'true').lower() == 'true'
    
    # Advanced Clustering Settings
    MIN_CLUSTER_SIZE = int(os.getenv('MIN_CLUSTER_SIZE', '3'))
    MIN_CLUSTER_DENSITY = float(os.getenv('MIN_CLUSTER_DENSITY', '0.25'))
    MIN_UNKNOWN_GAP_SIZE = int(os.getenv('MIN_UNKNOWN_GAP_SIZE', '6'))

    # Temporal Overlap Resolution
    OVERLAP_RESOLUTION_ENABLED = os.getenv('OVERLAP_RESOLUTION_ENABLED', 'true').lower() == 'true'
    OVERLAP_THRESHOLD = float(os.getenv('OVERLAP_THRESHOLD', '0.3'))

    # Offset agreement (D07): keep a cluster only when at least this many of its
    # detections agree on where they are in the track, i.e. their set time minus
    # the provider's match offset lies within OFFSET_AGREEMENT_SECONDS of one
    # another. The cluster keeps only the largest such agreeing group.
    # 0 disables (legacy behaviour).
    OFFSET_AGREEMENT_MIN = int(os.getenv('OFFSET_AGREEMENT_MIN', '0'))
    OFFSET_AGREEMENT_SECONDS = float(os.getenv('OFFSET_AGREEMENT_SECONDS', '4'))
    # D07b timing: offset agreement decides whether a track is kept, but a kept
    # track's start and end come from all of its detections that connect to the
    # agreeing group with gaps of at most this many windows. Early detections of
    # pitched tracks drift and looped sections match elsewhere in the track, so
    # they rarely agree; timing from the agreeing group alone started tracks late
    # (Russell's Yoon listening, 2026-11-25). 0 disables.
    # Mode 'span' changes only start/end; 'cluster' also counts the detections.
    OFFSET_TIMING_EXTEND_WINDOWS = int(os.getenv('OFFSET_TIMING_EXTEND_WINDOWS', '0'))
    OFFSET_TIMING_EXTEND_MODE = os.getenv('OFFSET_TIMING_EXTEND_MODE', 'span').strip().lower()

    # Duplicate-version merge (D07): entries with the same artist and the same
    # title before any bracketed version tag, starting within this many seconds,
    # collapse to the one with most detections (the later one on a tie). Catches
    # the same track listed twice and the next track's remix bleeding in early.
    # 0 disables.
    DUPLICATE_MERGE_SECONDS = float(os.getenv('DUPLICATE_MERGE_SECONDS', '0'))

    # Combined false-positive score (D07, false_positive_score.py): drop final
    # entries scoring below this. 0 disables. Corpus frontier (108 sets):
    # 0.30 trims ~28 wrong entries for 2 real tracks; 0.50 trims ~95 for 40;
    # 0.55 trims ~122 for 71 (first point at net false positives <= 0 vs
    # Production live).
    FALSE_POSITIVE_SCORE_MIN = float(os.getenv('FALSE_POSITIVE_SCORE_MIN', '0'))

    # Named clustering profile. Empty keeps the settings above unchanged.
    CLUSTERING_PROFILE = os.getenv('CLUSTERING_PROFILE', '').strip().lower()

    # Base Paths (changed from TEMP_DIR to ASSETS_DIR)
    ASSETS_DIR = Path('assets')
    OUTPUT_DIR = Path('output')
    CHECKPOINT_DIR = Path('checkpoints')
    
    @classmethod
    def validate(cls):
        """Validate configuration and return status."""
        issues = []
        
        if cls.ENABLE_SPOTIFY and (not cls.SPOTIFY_CLIENT_ID or not cls.SPOTIFY_CLIENT_SECRET):
            issues.append("Spotify enabled but credentials missing")
        
        if cls.ENABLE_DISCOGS and not cls.DISCOGS_TOKEN and not (cls.DISCOGS_CONSUMER_KEY and cls.DISCOGS_CONSUMER_SECRET):
            issues.append("Discogs enabled but credentials missing (set DISCOGS_TOKEN or DISCOGS_CONSUMER_KEY + DISCOGS_CONSUMER_SECRET)")

        return issues
    
    @classmethod
    def ensure_directories(cls):
        """Create necessary base directories."""
        cls.ASSETS_DIR.mkdir(exist_ok=True)
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.CHECKPOINT_DIR.mkdir(exist_ok=True)
    


# D07 round 3 (45 public mixes scored against their own tracklists): offset
# agreement replaces the detection-count and density rules. Overlap resolution
# stays on: after the offset filter it is accuracy-neutral and keeps the
# timeline free of overlapping entries.
CLUSTERING_PROFILES = {
    'offset_agreement': {
        'MIN_CLUSTER_SIZE': 1,
        'MIN_CLUSTER_DENSITY': 0.0,
        'OFFSET_AGREEMENT_MIN': 2,
        # D07b (Russell, 2026-11-25): time kept tracks from connected detections.
        'OFFSET_TIMING_EXTEND_WINDOWS': 8,
        'OFFSET_TIMING_EXTEND_MODE': 'span',
        'DUPLICATE_MERGE_SECONDS': 300.0,
        'FALSE_POSITIVE_SCORE_MIN': 0.30,
    },
}


def apply_clustering_profile(name: str) -> None:
    if not name:
        return
    if name not in CLUSTERING_PROFILES:
        raise ValueError(f'Unknown CLUSTERING_PROFILE: {name}')
    for key, value in CLUSTERING_PROFILES[name].items():
        setattr(Config, key, value)


apply_clustering_profile(Config.CLUSTERING_PROFILE)
