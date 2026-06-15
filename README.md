# Hermes Spotify Listening Profile Plugin

A Hermes Agent plugin that tracks your Spotify listening activity in the background and builds a personal listening profile. 

This plugin runs entirely locally and offline-first, capturing your listening habits across all your devices (PC, phone, commute) without relying on real-time webhooks or external databases.

## Features

- **Background Tracking:** An hourly daemon poller quietly pulls your Spotify `recently_played` history.
- **Offline-First:** By leveraging Spotify's 50-track server-side buffer, you don't lose data when the Hermes host PC is asleep (e.g., during your commute).
- **Fast Tooling:** After every poll, the plugin aggregates the raw history into a lightweight JSON profile block. The `listening_profile` tool can instantly read these blocks to give you stats and trends over any time window.
- **Skip Detection:** Automatically detects if you skipped a song based on timestamp gaps vs. track duration.

*(Note: Audio feature analysis like Energy, BPM, and Valence are not included as Spotify permanently deprecated the `/v1/audio-features` endpoint in late 2024.)*

## Installation

This plugin requires the core `spotify` plugin to be enabled and authenticated, as it reuses the underlying Spotify Client credentials.

1. Clone the plugin into your Hermes plugins directory:
   ```bash
   git clone https://github.com/Driebble/hermes-spotify-listening-profile.git ~/.hermes/plugins/hermes-spotify-listening-profile
   ```
2. Ensure the `spotify` plugin is enabled in your `config.yaml`.
3. Ensure you have authenticated via `hermes auth add spotify`.
4. Enable this plugin by adding it to your `config.yaml`:
   ```yaml
   plugins:
     enabled:
       - hermes-spotify-listening-profile
   ```
5. Restart your Hermes gateway process.

## Environment Variables

You can optionally configure the behavior by adding these to your profile's `.env` file:

| Variable | Default | Description |
|----------|---------|-------------|
| `LISTENING_PROFILE_POLL_INTERVAL` | `60` | Poll frequency in minutes (default is 60 minutes). The system enforces a hard minimum of 1 minute to prevent rate-limiting. |
| `LISTENING_PROFILE_SKIP_THRESHOLD` | `0.5` | Minimum listen ratio to count as a full listen (0.0 to 1.0). Tracks skipped before 50% are flagged as skips. |
## Usage

You or your agent can query your listening data at any time using the `listening_profile` tool. All queries automatically trigger an immediate Spotify poll before returning results, so the data is always fresh:

- **Profile:** Generate a full summary of your top artists, tracks, and time-of-day blocks in pure JSON.
  ```json
  {"query": "profile", "days": 7}
  ```
- **Stats:** Fast, top-level numbers (total plays, minutes listened, skip rate).
  ```json
  {"query": "stats", "days": 30}
  ```
- **Trends:** Compare two time windows to see changes in your habits or newly discovered artists. Compares the last N days against the previous N days.
  ```json
  {"query": "trends", "days": 7}
  ```
- **History:** Paginated raw track log.
  ```json
  {"query": "history", "limit": 20}
  ```

## File Structure

Data is stored alongside your Hermes profile logs:
- `logs/listening-history/YYYY-MM-DD.jsonl` — Raw, deduplicated play events.
- `logs/listening-profile/YYYY-MM-DD.json` — Lightweight daily aggregations.

See [SPEC.md](SPEC.md) for deeper architectural details on the poller and aggregation pipeline.