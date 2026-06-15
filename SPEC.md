# hermes-listening-profile

> A Hermes plugin that tracks Spotify listening activity and builds a personal listening profile over time.

## Overview

Polls the Spotify `recently_played` API hourly, stores deduplicated listening history as daily JSONL, and generates a polished listening profile on a daily schedule. Exposes a `listening_profile` tool for on-demand queries.

## Architecture

```
Spotify API → Poller (hourly, daemon) → raw daily JSONL
                                            ↓
                              Profile Generator (daily cron)
                                            ↓
                              listening-profile.json  (machine-readable)
                              listening-profile.md    (human-readable)
                                            ↓
                              listening_profile tool (on-demand queries)
```

## Components

### 1. Poller (Background Daemon Thread)

- Runs as a daemon thread inside the Hermes process, dies with the gateway
- Polls Spotify `recently_played` (limit=50) on interval-aligned clock boundaries
- **Deduplicates** by `played_at` before writing — reads tail of current day's JSONL, builds set of existing timestamps, appends only new entries
- Writes to `logs/listening-profile/YYYY-MM-DD.jsonl` (daily files, append-only after dedup)
- PID lock prevents duplicate poller instances
- `atexit` cleanup on process exit

### 2. Profile Generator (Cron Job)

- Runs daily on a configurable schedule (default: 07:00 WIB)
- Reads all daily JSONL files within the lookback window
- Applies skip detection (timestamp gap heuristic)
- Batch-fetches audio features from Spotify `/audio-features` endpoint
- Computes aggregated stats, genre distribution, temporal patterns
- Outputs:
  - `listening-profile.json` — machine-readable profile (plugin root)
  - `listening-profile.md` — human-readable profile (plugin root)

### 3. Tool Handler (On-Demand)

Exposes the `listening_profile` tool with these queries:

| Query | Description |
|-------|-------------|
| `profile` | Returns the pre-computed profile (reads output files) |
| `history` | Raw listening history, time-range filtered, paginated |
| `stats` | Aggregated stats within a time window |
| `trends` | On-demand trend comparison between time windows |

## Storage

### Raw Data: `logs/listening-profile/YYYY-MM-DD.jsonl`

Daily JSONL files. Each line is one track play event with full Spotify API response:

```json
{
  "played_at": "2026-06-15T10:30:00.000Z",
  "track": {
    "id": "abc123",
    "name": "Song Name",
    "duration_ms": 240000,
    "popularity": 72,
    "explicit": false,
    "external_urls": { "spotify": "https://open.spotify.com/track/..." },
    "uri": "spotify:track:abc123"
  },
  "artists": [{ "id": "...", "name": "Artist Name" }],
  "album": {
    "id": "...",
    "name": "Album Name",
    "release_date": "2024-01-15",
    "album_type": "album",
    "images": [...]
  },
  "context": { "type": "playlist", "uri": "spotify:playlist:..." }
}
```

### Output: Plugin Root

- `listening-profile.json` — machine-readable profile
- `listening-profile.md` — human-readable profile

## Skip Detection

- **Heuristic:** Compare `played_at` gap between consecutive tracks against `duration_ms`
- Computed at read/aggregation time, not at poll time
- If `gap_to_next < duration_ms × SKIP_THRESHOLD` → flagged as likely skip
- `listen_ratio = gap_to_next / duration_ms`, capped at 1.0
- Configurable via env var

## Audio Features

- Batch-fetched from Spotify `/audio-features` endpoint (up to 100 IDs per call)
- Features: tempo, energy, valence, danceability, acousticness, instrumentalness, speechiness, liveness, key, mode, time_signature
- Fetched during profile generation, not at poll time
- Cached in the generated profile, not stored per-entry in raw JSONL

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LISTENING_PROFILE_POLL_INTERVAL` | `3600` | Poll frequency in seconds |
| `LISTENING_PROFILE_SKIP_THRESHOLD` | `0.5` | Minimum listen ratio to count as full listen (0.0–1.0) |
| `LISTENING_PROFILE_GENERATE_TIME` | `0700` | Daily profile generation time (24h format, local time) |

## Tool Query Details

### `history`
- Parameters: `days` (default: 7, max: 30), `limit` (entries per page, default: 50)
- Loads only daily JSONL files within the time window
- Returns paginated track play events with timestamps

### `profile`
- No parameters needed
- Returns the pre-computed `listening-profile.json` contents
- Always fresh (regenerated daily at configured time)

### `stats`
- Parameters: `days` (default: 7)
- Returns: top artists, top tracks, total listening minutes, unique tracks, skip rate

### `trends`
- Parameters: `compare` (e.g., "this_week vs last_week", "this_month vs last_month")
- On-demand comparison of listening patterns between two time windows
- Returns: genre shifts, artist discovery changes, energy/valence deltas

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Spotify API only | One source of truth, no merge logic |
| Poll frequency | Hourly (configurable) | 50-track buffer covers ~3h; hourly polls never miss |
| Dedup | In-poller, by `played_at` | Keeps JSONL clean without post-processing |
| Storage format | Daily JSONL | Simple, append-friendly, easy to filter by date |
| Skip detection | On read, timestamp gap | Can't compute at poll time without modifying written entries |
| Audio features | On demand during generation | Batch-efficient, no per-poll overhead |
| Profile generation | Daily cron at 07:00 | Pre-computed for other tools, fresh by morning |
| Output location | Plugin root | Easy access for other tools and queries |
| Trend analysis | On-demand tool query | No clear need for pre-computed trends yet |

## File Structure

```
hermes-listening-profile/
├── __init__.py              # register(ctx) → start poller + register tool
├── poller.py                # ListeningPoller daemon thread
├── tools.py                 # listening_profile tool handler
├── schemas.py               # Tool schema definition
├── SPEC.md                  # This file
├── listening-profile.json   # Generated profile (machine-readable)
└── listening-profile.md     # Generated profile (human-readable)
```

## Plugin Enable/Disable

Managed through Hermes `config.yaml`, not env vars. When the plugin is loaded by Hermes, the poller starts automatically.
