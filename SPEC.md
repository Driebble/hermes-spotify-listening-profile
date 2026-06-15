# hermes-listening-profile

> A Hermes plugin that tracks Spotify listening activity and builds a personal listening profile over time.

## Overview

Polls the Spotify `recently_played` API on a schedule, stores listening history, and processes it into a listening profile that captures taste, patterns, and mood over time.

## Data Source

- **Spotify Web API** — `recently_played` endpoint
- Returns last 50 tracks per call with `played_at` timestamps, track metadata, artist info, and album data
- Single source of truth — no merge with Discord activity tracker

## Components

### 1. Poller

- Runs on a cron schedule (hourly)
- Calls Spotify `recently_played` (limit=50)
- Appends results to JSONL storage, deduplicating by `played_at` timestamp
- Each entry captures: track name, artist(s), album, `played_at`, `duration_ms`, `track_id`, `popularity`

### 2. Audio Features Enrichment

- Fetches audio features in batch via `/audio-features` (up to 100 track IDs per call)
- Features: tempo, energy, valence, danceability, acousticness, instrumentalness, speechiness, liveness, key, mode, time_signature
- Fetched periodically (not every poll) — batch collect track IDs, then enrich in one call
- Stored alongside track data in the JSONL entries

### 3. Skip Detection

- **Heuristic:** Compare `played_at` gap between consecutive tracks against `duration_ms`
- If `gap_to_next < duration_ms × SKIP_THRESHOLD` → flagged as likely skip
- `listen_ratio = gap_to_next / duration_ms`, capped at 1.0
- Configurable via env var: `LISTENING_PROFILE_SKIP_THRESHOLD`
- Default threshold: `0.5` (50% of track duration)

### 4. Storage

- JSONL file, one record per track play
- Dedup key: `played_at` (Spotify-guaranteed unique)
- Append-only, no overwrites

### 5. Profile Algorithm

Processes stored listening history into a listening profile. (TBD — design in progress)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LISTENING_PROFILE_SKIP_THRESHOLD` | `0.5` | Minimum listen ratio to count as a full listen (0.0–1.0) |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Spotify API only | Simpler, one source of truth, no merge logic |
| Poll frequency | Hourly | 50-track buffer covers ~3h; hourly polls never miss anything |
| Storage format | JSONL | Append-friendly, easy to process, consistent with Drie's preferences |
| Dedup strategy | `played_at` timestamp | Unique per play event, no ambiguity |
| Skip detection | Timestamp gap heuristic | Zero extra API calls, covers most cases |
| Skip threshold | 50% of duration (configurable) | Balances false positives vs catching real skips |
| Audio features | Batch fetch, periodic enrichment | Efficient — up to 100 IDs per call, no per-track overhead |

## Open Questions

- [ ] Profile output format and structure (JSON? Markdown? Both?)
- [ ] Temporal segmentation (commute vs work vs night — or raw timestamps?)
- [ ] How often to rebuild the profile
- [ ] Where to store the processed profile output
