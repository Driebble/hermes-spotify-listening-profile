"""Poller for Spotify recently_played. Runs as a daemon thread."""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

# Note: Uses the existing Spotify plugin client.
try:
    from plugins.spotify.client import SpotifyClient, SpotifyError
except ImportError:
    SpotifyClient = None
    SpotifyError = Exception


def _is_process_alive(pid: int) -> bool:
    """Check if a process is still running (cross-platform)."""
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x100000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


class ListeningPoller:
    """Background thread that polls Spotify recently_played and writes daily JSONL."""

    def __init__(self, poll_interval: int, history_dir: Path, profile_dir: Path):
        self.poll_interval = poll_interval
        self.history_dir = Path(history_dir)
        self.profile_dir = Path(profile_dir)
        self._stop = threading.Event()
        self._thread = None
        self._started = False
        self._poll_count = 0
        self._error_count = 0
        self._profile_lock = threading.Lock()
        
        try:
            self._skip_threshold = float(os.environ.get("LISTENING_PROFILE_SKIP_THRESHOLD", "0.5"))
        except ValueError:
            self._skip_threshold = 0.5

    def start(self):
        """Start the polling thread (only if not already running)."""
        if not SpotifyClient:
            print("[listening-profile] Cannot start poller: Spotify plugin not found.")
            return

        lock_file = self.history_dir / ".poller.lock"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

        if lock_file.exists():
            try:
                old_pid = int(lock_file.read_text().strip())
                # If the PID is different and that process is still running, lock it.
                # If the PID matches our own, the previous thread in this process was 
                # either stopped or lost during a reload. We should proceed.
                if old_pid != os.getpid() and _is_process_alive(old_pid):
                    return
            except (ValueError, OSError):
                pass

        lock_file.write_text(str(os.getpid()))
        self._lock_file = lock_file

        self._thread = threading.Thread(target=self._run, daemon=True, name="listening-profile-poller")
        self._thread.start()
        self._started = True
        print(f"[listening-profile] Poller started (every {self.poll_interval}s)")

    def stop(self):
        """Signal the polling thread to stop and wait for it."""
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

        if self._started and hasattr(self, "_lock_file") and self._lock_file and self._lock_file.exists():
            try:
                stored_pid = int(self._lock_file.read_text().strip())
                if stored_pid == os.getpid():
                    self._lock_file.unlink()
            except (ValueError, OSError):
                pass

        if self._started:
            print(f"[listening-profile] Poller stopped (polls: {self._poll_count}, errors: {self._error_count})")

    def _get_existing_timestamps(self) -> set[str]:
        """Read the current day's JSONL to find timestamps we already have."""
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        log_file = self.history_dir / f"{today}.jsonl"
        timestamps = set()
        
        if not log_file.exists():
            return timestamps

        # We only really need the tail, but reading the whole day's file is cheap.
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if "played_at" in entry:
                            timestamps.add(entry["played_at"])
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass

        return timestamps

    def _run(self):
        """Main polling loop — runs in a background thread."""
        client = SpotifyClient()

        while not self._stop.is_set():
            # Align polling to interval boundaries
            now = datetime.now().astimezone()
            elapsed_in_interval = (now.minute * 60 + now.second) % self.poll_interval
            wait = self.poll_interval - elapsed_in_interval - now.microsecond / 1_000_000
            
            # Start right away if this is the first run, otherwise wait.
            if self._poll_count > 0 and wait > 0:
                self._stop.wait(wait)
            
            if self._stop.is_set():
                break

            try:
                data = client.get_recently_played(limit=50)
                if data and "items" in data:
                    items = data["items"]
                    # Reverse so chronological (oldest to newest)
                    items.reverse()
                    
                    existing_timestamps = self._get_existing_timestamps()
                    new_items = [i for i in items if i.get("played_at") not in existing_timestamps]

                    if new_items:
                        self._process_and_save_items(client, new_items)
                
                self._error_count = 0  # reset consecutive errors
            except SpotifyError as e:
                self._error_count += 1
                if self._error_count <= 3:
                    print(f"[listening-profile] Spotify API error: {e}")
            except Exception as e:
                self._error_count += 1
                if self._error_count <= 3:
                    print(f"[listening-profile] Poller error: {e}")
            finally:
                self._poll_count += 1  # Always increment to prevent tight spin on errors

    def _process_and_save_items(self, client: SpotifyClient, new_items: list[dict]):
        """Save new items to JSONL grouped by played_at day, aggregate per-day profile."""
        from collections import defaultdict
        
        # Group items by their actual played_at date (UTC, Spotify format is YYYY-MM-DDTHH:MM:SS.mmmZ)
        items_by_day = defaultdict(list)
        for item in new_items:
            ts = item.get("played_at", "")
            if not ts:
                continue
            play_date = ts[:10]  # YYYY-MM-DD prefix
            items_by_day[play_date].append(item)
        
        for play_date, day_items in items_by_day.items():
            log_file = self.history_dir / f"{play_date}.jsonl"
            existing_ts = set()
            
            if log_file.exists():
                try:
                    with open(log_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                if "played_at" in entry:
                                    existing_ts.add(entry["played_at"])
                            except json.JSONDecodeError:
                                pass
                except OSError:
                    pass
            
            truly_new = [i for i in day_items if i.get("played_at") not in existing_ts]
            if not truly_new:
                continue
            
            with open(log_file, "a", encoding="utf-8") as f:
                for item in truly_new:
                    track = item.get("track", {})
                    # Prune massive unused fields to save disk space and LLM context
                    if "available_markets" in track:
                        track.pop("available_markets", None)
                    if "album" in track and "available_markets" in track["album"]:
                        track["album"].pop("available_markets", None)
                    
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            
            # Roll up the profile for THIS play_date (not today)
            self._generate_daily_profile(play_date)

    def poll_now(self) -> int:
        """Trigger an immediate poll on demand. Returns number of new tracks fetched."""
        if not SpotifyClient:
            return 0
        client = SpotifyClient()
        new_count = 0
        try:
            data = client.get_recently_played(limit=50)
            if data and "items" in data:
                items = data["items"]
                items.reverse()
                existing_timestamps = self._get_existing_timestamps()
                new_items = [i for i in items if i.get("played_at") not in existing_timestamps]
                if new_items:
                    self._process_and_save_items(client, new_items)
                    new_count = len(new_items)
                else:
                    # No new tracks but still re-aggregate in case the aggregation logic changed
                    today = datetime.now().astimezone().strftime("%Y-%m-%d")
                    self._generate_daily_profile(today)
        except Exception as e:
            print(f"[listening-profile] On-demand poll error: {e}")
        return new_count

    def _get_time_block(self, dt: datetime) -> str:
        hour = dt.hour
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 22:
            return "evening"
        else:
            return "night"

    def _generate_daily_profile(self, target_date: str):
        """Read target date's history, compute skips and aggregate into JSON profile."""
        from collections import defaultdict
        
        filepath = self.history_dir / f"{target_date}.jsonl"
        if not filepath.exists():
            return
            
        entries = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts_str = entry.get("played_at")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone()
                        entry["_dt"] = ts
                        entries.append(entry)
                except (json.JSONDecodeError, ValueError):
                    continue
                    
        entries.sort(key=lambda e: e["_dt"])
        
        # Apply skip detection
        for i in range(len(entries)):
            current = entries[i]
            duration_ms = current.get("track", {}).get("duration_ms", 0)
            if duration_ms == 0:
                current["listen_ratio"] = 1.0
                current["is_skip"] = False
                continue
                
            if i + 1 < len(entries):
                next_entry = entries[i + 1]
                gap_ms = (next_entry["_dt"] - current["_dt"]).total_seconds() * 1000
                ratio = gap_ms / duration_ms
                current["listen_ratio"] = min(1.0, ratio)
                current["is_skip"] = ratio < self._skip_threshold
            else:
                current["listen_ratio"] = 1.0
                current["is_skip"] = False
                
        # Aggregate
        total_entries = len(entries)
        full_listens = [e for e in entries if not e.get("is_skip", False)]
        listening_ms = sum(e.get("track", {}).get("duration_ms", 0) for e in full_listens)
        
        artist_counts = defaultdict(int)
        track_counts = defaultdict(int)
        track_map = {}
        
        time_blocks = {
            "morning": {"plays": 0},
            "afternoon": {"plays": 0},
            "evening": {"plays": 0},
            "night": {"plays": 0},
        }
        
        # New aggregations
        popularity_sum = 0
        popularity_count = 0
        explicit_plays = 0
        context_types = defaultdict(int)
        album_counts = defaultdict(int)
        album_map = {}
        release_years = defaultdict(int)
        seen_artist_ids = set()
        known_artist_ids = set()
        
        for e in full_listens:
            track = e.get("track") or {}
            track_name = track.get("name")
            track_id = track.get("id")
            artists = track.get("artists") or []
            dt = e.get("_dt")
            context = e.get("context") or {}
            album = track.get("album") or {}
            
            if not track_id:
                continue
                
            track_map[track_id] = track_name
            track_counts[track_id] += 1
            
            # Popularity
            pop = track.get("popularity")
            if pop is not None:
                popularity_sum += pop
                popularity_count += 1
                
            # Explicit
            if track.get("explicit"):
                explicit_plays += 1
                
            # Context type
            ctx_type = context.get("type", "unknown")
            context_types[ctx_type] += 1
            
            # Albums
            album_id = album.get("id")
            album_name = album.get("name")
            if album_id and album_name:
                album_map[album_id] = album_name
                album_counts[album_id] += 1
                
            # Release year
            release_date = album.get("release_date", "")
            if release_date and len(release_date) >= 4:
                try:
                    year = int(release_date[:4])
                    release_years[year] += 1
                except ValueError:
                    pass
                    
            # Artist discovery tracking
            for a in artists:
                name = a.get("name")
                artist_id = a.get("id")
                if name:
                    artist_counts[name] += 1
                if artist_id:
                    if artist_id in seen_artist_ids:
                        known_artist_ids.add(artist_id)
                    seen_artist_ids.add(artist_id)
                    
            if dt:
                block_name = self._get_time_block(dt)
                time_blocks[block_name]["plays"] += 1
                
        tracks_out = {tid: {"name": track_map[tid], "plays": count} for tid, count in track_counts.items()}
        albums_out = {aid: {"name": album_map[aid], "plays": count} for aid, count in album_counts.items()}
        
        new_artist_ids = seen_artist_ids - known_artist_ids
        
        # Average popularity
        avg_popularity = round(popularity_sum / popularity_count) if popularity_count > 0 else 0
        
        # Release year breakdown (recent = last 2 years, catalog = older)
        current_year = datetime.now().astimezone().year
        recent_releases = sum(count for year, count in release_years.items() if year >= current_year - 1)
        catalog_releases = sum(count for year, count in release_years.items() if year < current_year - 1)
        
        profile_data = {
            "date": target_date,
            "daily_totals": {
                "total_plays": total_entries,
                "full_listens": len(full_listens),
                "listening_minutes": round(listening_ms / 60000)
            },
            "artists": dict(artist_counts),
            "tracks": tracks_out,
            "albums": albums_out,
            "time_blocks": time_blocks,
            "context_types": dict(context_types),
            "popularity": {
                "average": avg_popularity
            },
            "explicit_ratio": {
                "explicit": explicit_plays,
                "clean": len(full_listens) - explicit_plays
            },
            "release_years": dict(release_years),
            "new_vs_catalog": {
                "recent": recent_releases,
                "catalog": catalog_releases
            },
            "new_artists": len(new_artist_ids)
        }
        
        json_path = self.profile_dir / f"{target_date}.json"
        with self._profile_lock:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(profile_data, f, indent=2, ensure_ascii=False)
