# hermes-listening-profile

> A Hermes plugin that tracks Spotify listening activity and builds a personal listening profile over time.

## Overview

Polls the Spotify `recently_played` API hourly, stores deduplicated listening history as daily JSONL, and generates a polished listening profile daily. Exposes a `listening_profile` tool for on-demand queries. Fully self-contained — two daemon threads (poller + generator) that live and die with the gateway.

## Architecture

```
Spotify API → Poller (hourly, daemon) → raw daily JSONL + audio features
                                              ↓
                                Generator (daily, daemon)
                                              ↓
                                listening-profile.json  (machine-readable)
                                listening-profile.md    (human-readable)
                                              ↓
                                listening_profile tool (on-demand queries)
```

## Components

### 1. Poller (Daemon Thread)

- Runs as a daemon thread inside the Hermes process, dies with the gateway
- Polls Spotify `recently_played` (limit=50) on interval-aligned clock boundaries
- **Deduplicates** by `played_at` — reads tail of current day's JSONL, builds set of existing timestamps, appends only new entries
- For new (deduped) tracks: **batch-fetches audio features** from Spotify `/audio-features` endpoint (up to 100 IDs per call)
- Writes self-contained entries to `logs/listening-profile/YYYY-MM-DD.jsonl`
- PID lock prevents duplicate poller instances
- `atexit` cleanup on process exit

### 2. Generator (Daemon Thread)

- Runs as a daemon thread inside the Hermes process, dies with the gateway
- Sleeps until the configured generation time (default: 07:00), wakes up, generates profile, goes back to sleep
- Reads daily JSONL files up to **12 months** of history
- Applies skip detection (timestamp gap heuristic)
- Computes aggregated stats from pre-existing audio features (no API calls)
- **Retry logic:** up to `LISTENING_PROFILE_MAX_RETRIES` attempts (default: 3) on failure, logs error if all retries fail
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
| `trends` | On-demand trend comparison between two time windows |

**Zero Spotify API calls** at query time — all data comes from JSONL files or the pre-computed profile.

## Storage

### Raw Data: `logs/listening-profile/YYYY-MM-DD.jsonl`

Daily JSONL files. Each line is one track play event with full Spotify response + audio features:

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
  "context": { "type": "playlist", "uri": "spotify:playlist:..." },
  "audio_features": {
    "tempo": 128.5,
    "energy": 0.82,
    "valence": 0.65,
    "danceability": 0.74,
    "acousticness": 0.12,
    "instrumentalness": 0.03,
    "speechiness": 0.04,
    "liveness": 0.11,
    "key": 5,
    "mode": 1,
    "time_signature": 4
  }
}
```

### Output: Plugin Root

- `listening-profile.json` — machine-readable profile
- `listening-profile.md` — human-readable profile

## Skip Detection

- **Heuristic:** Compare `played_at` gap between consecutive tracks against `duration_ms`
- Computed at aggregation time (generator + tool queries), not at poll time
- If `gap_to_next < duration_ms × SKIP_THRESHOLD` → flagged as likely skip
- `listen_ratio = gap_to_next / duration_ms`, capped at 1.0
- Configurable via env var

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LISTENING_PROFILE_POLL_INTERVAL` | `3600` | Poll frequency in seconds |
| `LISTENING_PROFILE_SKIP_THRESHOLD` | `0.5` | Minimum listen ratio to count as full listen (0.0–1.0) |
| `LISTENING_PROFILE_GENERATE_TIME` | `0700` | Daily profile generation time (24h format, local time) |
| `LISTENING_PROFILE_MAX_RETRIES` | `3` | Max retry attempts for profile generation on failure |

## Tool Query Details

### `history`
- Parameters: `days` (default: 7, max: 30), `limit` (entries per page, default: 50), `offset` (skip N entries, default: 0)
- Loads only daily JSONL files within the time window
- Returns paginated track play events with `total` count for pagination

### `profile`
- No parameters needed
- Returns the pre-computed `listening-profile.json` contents

### `stats`
- Parameters: `days` (default: 7)
- Returns: top artists, top tracks, total listening minutes, unique tracks, skip rate

### `trends`
- Parameters: `preset` — one of `weekly`, `biweekly`, `monthly`
  - `weekly`: last 7 days vs 7 days before that
  - `biweekly`: last 14 days vs 14 days before that
  - `monthly`: last 30 days vs 30 days before that
- Returns: genre shifts, artist discovery changes, energy/valence deltas
- If insufficient data (JSONL files don't cover both windows), returns `{"error": "Not enough data for trends"}`

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Data source | Spotify API only | One source of truth, no merge logic |
| Poll frequency | Hourly (configurable) | 50-track buffer covers ~3h; hourly polls never miss |
| Dedup | In-poller, by `played_at` | Keeps JSONL clean without post-processing |
| Audio features | In-poller, per new track | Single API contact point, all downstream is pure file reads |
| Storage format | Daily JSONL | Simple, append-friendly, easy to filter by date |
| Skip detection | On read/aggregation | Can't compute at poll time without modifying written entries |
| Profile generation | Daemon thread in plugin | Self-contained, starts/stops with gateway, no separate cron |
| Output location | Plugin root | Easy access for other tools and queries |
| Trend analysis | On-demand tool query | 3 presets, no pre-computed trends needed |
| History lookback | 12 months max | Balances completeness vs file scanning overhead |
| Plugin enable/disable | Hermes config.yaml | Standard plugin pattern, no env var needed |

## File Structure

```
hermes-listening-profile/
├── __init__.py              # register(ctx) → start poller + generator + register tool
├── poller.py                # ListeningPoller daemon thread
├── generator.py             # ProfileGenerator daemon thread
├── tools.py                 # listening_profile tool handler
├── schemas.py               # Tool schema definition
├── SPEC.md                  # This file
├── listening-profile.json   # Generated profile (machine-readable)
└── listening-profile.md     # Generated profile (human-readable)
```
