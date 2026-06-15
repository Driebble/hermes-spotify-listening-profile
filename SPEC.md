# hermes-listening-profile

> A Hermes plugin that tracks Spotify listening activity and builds personal listening profiles with real-time aggregation.

## Overview

The plugin captures raw listening history and rolls it up into daily profile snapshots. Tools dynamically aggregate these daily snapshots to generate profiles for any time window (weekly, monthly, all-time) in milliseconds.

## Architecture

```
Spotify API → Poller (hourly) → logs/listening-history/YYYY-MM-DD.jsonl
                                      ↓
                         (Immediate Aggregation) 
                                      ↓
                              logs/listening-profile/YYYY-MM-DD.json
                                      ↓
                listening_profile Tool dynamically aggregates blocks
```

## Components

### 1. Poller (Daemon Thread)
- Polls `recently_played` hourly on clock boundaries.
- Deduplicates using `played_at` timestamps.
- Prunes massive unused fields (like `available_markets`) to save disk space and LLM context.
- Writes raw data to `logs/listening-history/YYYY-MM-DD.jsonl`.
- Immediately after polling and writing new tracks, reads *today's* `listening-history` JSONL.
- Applies skip detection based on timestamp gaps vs. track duration.
- Rolls data into four hardcoded time blocks (Morning, Afternoon, Evening, Night).
- Saves a compact aggregate to `logs/listening-profile/YYYY-MM-DD.json`.

### 2. Tool Handler (On-Demand)
- Reads the lightweight `.json` files, not the heavy `.jsonl` files (except for explicit history requests).
- Instantly generates profiles, top tracks, top artists, and trend comparisons for any time scale.

## Storage Formats

### 1. Raw History (`logs/listening-history/YYYY-MM-DD.jsonl`)
Standard Spotify track object. One line per play event.

### 2. Profile Block (`logs/listening-profile/YYYY-MM-DD.json`)
```json
{
  "date": "2026-06-15",
  "daily_totals": {
    "total_plays": 45,
    "full_listens": 42,
    "listening_minutes": 142
  },
  "artists": {
    "The Strike": 7,
    "London Elektricity": 2
  },
  "tracks": {
    "5cCjEHVU0cx...": {"name": "The Getaway - M10 Version", "plays": 7}
  },
  "time_blocks": {
    "morning": {"plays": 12},
    "afternoon": {"plays": 20},
    "evening": {"plays": 10},
    "night": {"plays": 3}
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LISTENING_PROFILE_POLL_INTERVAL` | `60` | Poll frequency in minutes (minimum: 1) |
| `LISTENING_PROFILE_SKIP_THRESHOLD` | `0.5` | Minimum listen ratio to count as full listen (0.0–1.0) |

## Tool Queries

| Query | Description | Data Source |
|-------|-------------|-------------|
| `profile` | Generates full JSON profile for a time window | `listening-profile/*.json` |
| `history` | Paginated raw track log | `listening-history/*.jsonl` |
| `stats` | Fast top-level stats | `listening-profile/*.json` |
| `trends` | Delta comparing last N days vs previous N days | `listening-profile/*.json` |

All queries trigger an immediate Spotify poll before returning results, ensuring the freshest data is always included.

## Design Decisions
- **Offline-First Polling**: Using hourly polling on the `recently_played` REST endpoint guarantees data capture even when the host PC is asleep (e.g., during commutes), leveraging Spotify's 50-track server-side buffer to fill the gaps.
- **Time Blocks**: Hardcoded. Simpler, requires zero configuration, instantly maps to human rhythms.
- **No Audio Features**: Spotify deprecated and removed the `/v1/audio-features` endpoint in late 2024. Consequently, sonic fingerprinting (Energy, BPM, Valence) has been explicitly excluded from this architecture to prevent API rejections and maintain speed.