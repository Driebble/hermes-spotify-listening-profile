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

### 2. Storage

- JSONL file, one record per track play
- Dedup key: `played_at` (Spotify-guaranteed unique)
- Append-only, no overwrites

### 3. Profile Algorithm

Processes stored listening history into a listening profile. (TBD — design in progress)

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Spotify API only | Simpler, one source of truth, no merge logic |
| Poll frequency | Hourly | 50-track buffer covers ~3h; hourly polls never miss anything |
| Storage format | JSONL | Append-friendly, easy to process, consistent with Drie's preferences |
| Dedup strategy | `played_at` timestamp | Unique per play event, no ambiguity |

## Open Questions

- [ ] Profile output format and structure
- [ ] What metrics to include in the profile
- [ ] How to handle audio features (Spotify provides tempo, energy, valence, danceability, etc.)
- [ ] Temporal segmentation (commute vs work vs night)
- [ ] How often to rebuild the profile
- [ ] Where to store the processed profile output
