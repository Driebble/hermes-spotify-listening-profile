"""Tool handlers for the listening-profile plugin."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


# Module-level reference to the active poller, set by __init__.register()
_active_poller = None


def _get_history_dir() -> Path:
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        def get_hermes_home() -> Path:
            val = (os.environ.get("HERMES_HOME") or "").strip()
            return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()
    return get_hermes_home() / "logs" / "listening-history"


def _get_profile_dir() -> Path:
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        def get_hermes_home() -> Path:
            val = (os.environ.get("HERMES_HOME") or "").strip()
            return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()
    return get_hermes_home() / "logs" / "listening-profile"


def _load_daily_profiles(profile_dir: Path, days: int) -> list[dict]:
    """Load pre-aggregated daily profiles up to N days back."""
    profiles = []
    if not profile_dir.exists():
        return profiles
        
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    cutoff_date = cutoff.strftime("%Y-%m-%d")

    profile_files = sorted(
        [f for f in os.listdir(profile_dir) if f.endswith(".json")]
    )

    for filename in profile_files:
        file_date = filename.removesuffix(".json")
        if file_date < cutoff_date:
            continue
            
        filepath = profile_dir / filename
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                profiles.append(data)
        except (json.JSONDecodeError, OSError):
            continue
                
    return profiles


def _aggregate_multiple_profiles(profiles: list[dict]) -> dict:
    """Combine multiple daily profile dicts into one master aggregate."""
    total_plays = 0
    full_listens = 0
    listening_minutes = 0
    
    artist_counts = defaultdict(int)
    track_counts = defaultdict(lambda: {"name": "", "plays": 0})
    album_counts = defaultdict(lambda: {"name": "", "plays": 0})
    
    time_blocks = {
        "morning": {"plays": 0},
        "afternoon": {"plays": 0},
        "evening": {"plays": 0},
        "night": {"plays": 0},
    }
    
    context_types = defaultdict(int)
    popularity_sum = 0
    popularity_count = 0
    explicit_plays = 0
    clean_plays = 0
    release_years = defaultdict(int)
    recent_releases = 0
    catalog_releases = 0
    total_new_artists = 0
    
    for p in profiles:
        totals = p.get("daily_totals") or {}
        total_plays += totals.get("total_plays", 0)
        full_listens += totals.get("full_listens", 0)
        listening_minutes += totals.get("listening_minutes", 0)
        
        for artist, count in (p.get("artists") or {}).items():
            artist_counts[artist] += count
            
        for tid, track_info in (p.get("tracks") or {}).items():
            track_counts[tid]["name"] = track_info["name"]
            track_counts[tid]["plays"] += track_info["plays"]
            
        for aid, album_info in (p.get("albums") or {}).items():
            album_counts[aid]["name"] = album_info["name"]
            album_counts[aid]["plays"] += album_info["plays"]
            
        for block_name, block_data in (p.get("time_blocks") or {}).items():
            if block_name not in time_blocks:
                continue
            target_block = time_blocks[block_name]
            target_block["plays"] += (block_data or {}).get("plays", 0)
            
        for ctx_type, count in (p.get("context_types") or {}).items():
            context_types[ctx_type] += count
            
        pop = p.get("popularity") or {}
        avg = pop.get("average", 0)
        listens = totals.get("full_listens", 0)
        if avg > 0 and listens > 0:
            popularity_sum += avg * listens
            popularity_count += listens
            
        expl = p.get("explicit_ratio") or {}
        explicit_plays += expl.get("explicit", 0)
        clean_plays += expl.get("clean", 0)
        
        for year, count in (p.get("release_years") or {}).items():
            release_years[str(year)] += count
            
        nvc = p.get("new_vs_catalog") or {}
        recent_releases += nvc.get("recent", 0)
        catalog_releases += nvc.get("catalog", 0)
        
        total_new_artists += p.get("new_artists", 0)

    top_artists = [{"name": k, "plays": v} for k, v in sorted(artist_counts.items(), key=lambda x: -x[1])]
    top_tracks = [{"name": v["name"], "plays": v["plays"]} for tid, v in sorted(track_counts.items(), key=lambda x: -x[1]["plays"])]
    top_albums = [{"name": v["name"], "plays": v["plays"]} for aid, v in sorted(album_counts.items(), key=lambda x: -x[1]["plays"])]
    
    avg_popularity = round(popularity_sum / popularity_count) if popularity_count > 0 else 0
    
    time_blocks_resolved = {}
    for block_name, block_data in time_blocks.items():
        time_blocks_resolved[block_name] = {
            "plays": block_data["plays"]
        }

    return {
        "days_aggregated": len(profiles),
        "totals": {
            "total_plays": total_plays,
            "full_listens": full_listens,
            "listening_minutes": listening_minutes
        },
        "top_artists": top_artists[:20],
        "top_tracks": top_tracks[:20],
        "top_albums": top_albums[:20],
        "time_blocks": time_blocks_resolved,
        "context_types": dict(context_types),
        "popularity": {
            "average": avg_popularity
        },
        "explicit_ratio": {
            "explicit": explicit_plays,
            "clean": clean_plays
        },
        "release_years": dict(release_years),
        "new_vs_catalog": {
            "recent": recent_releases,
            "catalog": catalog_releases
        },
        "total_new_artists": total_new_artists
    }


def _query_profile(profile_dir: Path, days: int) -> str:
    """Generate profile on the fly from daily JSONs."""
    profiles = _load_daily_profiles(profile_dir, days)
    if not profiles:
        return json.dumps({"error": f"No daily profile data found for the last {days} days."})
        
    agg = _aggregate_multiple_profiles(profiles)
    
    return json.dumps({
        "data": agg
    }, ensure_ascii=False)


def _load_raw_entries(log_dir: Path, days: int) -> list[dict]:
    """Load JSONL history up to N days back (for history query only). Returns newest first."""
    entries = []
    if not log_dir.exists():
        return entries
        
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    cutoff_date = cutoff.strftime("%Y-%m-%d")

    log_files = sorted([f for f in os.listdir(log_dir) if f.endswith(".jsonl")])

    for filename in log_files:
        file_date = filename.removesuffix(".jsonl")
        if file_date < cutoff_date:
            continue
            
        filepath = log_dir / filename
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        ts_str = entry.get("played_at")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            if ts >= cutoff:
                                entry["_dt"] = ts
                                entries.append(entry)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            continue
                    
    entries.sort(key=lambda e: e["_dt"], reverse=True)
    return entries


def _query_history(history_dir: Path, days: int, limit: int, offset: int) -> str:
    """Return paginated raw track history."""
    entries = _load_raw_entries(history_dir, days)
    
    total = len(entries)
    page = entries[offset:offset + limit]
    
    # Strip to essential fields only
    items = []
    for p in page:
        track = p.get("track") or {}
        artists = [a.get("name", "") for a in (track.get("artists") or [])]
        album = track.get("album") or {}
        items.append({
            "played_at": p.get("played_at"),
            "track": track.get("name"),
            "artists": artists,
            "duration_ms": track.get("duration_ms"),
            "album": album.get("name"),
            "album_type": album.get("album_type"),
            "explicit": track.get("explicit"),
            "popularity": track.get("popularity"),
            "context_type": (p.get("context") or {}).get("type"),
        })
        
    return json.dumps({
        "total": total,
        "offset": offset,
        "limit": limit,
        "period_days": days,
        "items": items
    }, ensure_ascii=False)


def _query_stats(profile_dir: Path, days: int) -> str:
    """Fast top-level stats using the daily profiles."""
    profiles = _load_daily_profiles(profile_dir, days)
    if not profiles:
        return json.dumps({"error": f"No data found for the last {days} days."})
        
    agg = _aggregate_multiple_profiles(profiles)
    totals = agg["totals"]
    
    skip_rate = 0
    if totals["total_plays"] > 0:
        skip_count = totals["total_plays"] - totals["full_listens"]
        skip_rate = round((skip_count / totals["total_plays"]) * 100, 1)
        
    return json.dumps({
        "period_days": days,
        "total_plays": totals["total_plays"],
        "full_listens": totals["full_listens"],
        "skip_rate_percent": skip_rate,
        "listening_minutes": totals["listening_minutes"],
        "unique_tracks": len(agg["top_tracks"]),
        "unique_artists": len(agg["top_artists"]),
        "unique_albums": len(agg["top_albums"]),
        "top_artists": agg["top_artists"][:10],
        "top_tracks": agg["top_tracks"][:10],
        "top_albums": agg["top_albums"][:10],
        "context_types": agg["context_types"],
        "popularity": agg["popularity"],
        "explicit_ratio": agg["explicit_ratio"],
        "new_vs_catalog": agg["new_vs_catalog"],
        "total_new_artists": agg["total_new_artists"]
    }, ensure_ascii=False)


def _query_trends(profile_dir: Path, window_days: int) -> str:
    """Compare two time windows using the daily profiles."""
    total_lookback = window_days * 2
    profiles = _load_daily_profiles(profile_dir, total_lookback)
    
    if not profiles:
        return json.dumps({"error": f"No data found for trend comparison."})
        
    cutoff_date = (datetime.now().astimezone() - timedelta(days=window_days)).strftime("%Y-%m-%d")
    
    current_profiles = [p for p in profiles if p["date"] >= cutoff_date]
    previous_profiles = [p for p in profiles if p["date"] < cutoff_date]
    
    curr_agg = _aggregate_multiple_profiles(current_profiles)
    prev_agg = _aggregate_multiple_profiles(previous_profiles)
    
    prev_artists = {a.get("name") for a in prev_agg["top_artists"]}
    curr_artists = {a.get("name") for a in curr_agg["top_artists"]}
    new_discovery = list(curr_artists - prev_artists)
    
    return json.dumps({
        "window_days": window_days,
        "current_window": {
            "full_listens": curr_agg["totals"]["full_listens"],
            "unique_artists": len(curr_agg["top_artists"])
        },
        "previous_window": {
            "full_listens": prev_agg["totals"]["full_listens"],
            "unique_artists": len(prev_agg["top_artists"])
        },
        "new_artists_discovered": len(new_discovery),
        "new_artists": new_discovery
    }, ensure_ascii=False)


def _safe_int(val, default: int, min_val: int = 1, max_val: int = 9999) -> int:
    """Safely coerce a value to int with bounds."""
    try:
        return max(min_val, min(max_val, int(val)))
    except (TypeError, ValueError):
        return default


def _do_refresh() -> int:
    """Trigger an immediate poll via the module-level poller reference or new temporary instance. Returns new track count."""
    global _active_poller
    if _active_poller:
        try:
            return _active_poller.poll_now()
        except Exception:
            return 0
    else:
        # Fallback for worker subprocess environments where _active_poller reference is lost
        try:
            from .poller import ListeningPoller
            history_dir = _get_history_dir()
            profile_dir = _get_profile_dir()
            poller = ListeningPoller(
                poll_interval=3600,
                history_dir=history_dir,
                profile_dir=profile_dir
            )
            return poller.poll_now()
        except Exception:
            return 0


def listening_profile(args: dict, **kwargs) -> str:
    """Main tool handler."""
    query = args.get("query", "profile")
    days = _safe_int(args.get("days"), default=7, min_val=1, max_val=365)
    
    history_dir = _get_history_dir()
    profile_dir = _get_profile_dir()
    
    # Always trigger an immediate poll before returning results
    _do_refresh()
    
    try:
        if query == "profile":
            return _query_profile(profile_dir, days)
            
        elif query == "history":
            limit = _safe_int(args.get("limit"), default=50, min_val=1, max_val=500)
            offset = _safe_int(args.get("offset"), default=0, min_val=0)
            return _query_history(history_dir, days, limit, offset)
            
        elif query == "stats":
            return _query_stats(profile_dir, days)
            
        elif query == "trends":
            return _query_trends(profile_dir, days)

        else:
            return json.dumps({"error": f"Unknown query: {query}"})
            
    except Exception as e:
        return json.dumps({"error": f"Query failed: {e}"})
