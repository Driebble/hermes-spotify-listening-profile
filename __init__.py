"""Listening Profile Plugin — Spotify presence tracking and profiling.

Auto-starts a daemon thread when Hermes loads this plugin:
1. Poller: Polls Spotify recently_played hourly, appends to daily JSONL, and rolls up the profile for the day.

Exposes a listening_profile tool for querying history, stats, trends, and the profile.
"""

import os
import atexit
import traceback
from pathlib import Path

_LOG_FILE = Path(__file__).parent / "plugin.log"

def _log(msg: str):
    """Write to plugin.log for debugging."""
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _get_history_dir() -> Path:
    """Resolve history directory."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        def get_hermes_home() -> Path:
            val = (os.environ.get("HERMES_HOME") or "").strip()
            return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()
    return get_hermes_home() / "logs" / "listening-history"


def _get_profile_dir() -> Path:
    """Resolve profile directory."""
    try:
        from hermes_constants import get_hermes_home
    except ImportError:
        def get_hermes_home() -> Path:
            val = (os.environ.get("HERMES_HOME") or "").strip()
            return Path(val).resolve() if val else (Path.home() / ".hermes").resolve()
    return get_hermes_home() / "logs" / "listening-profile"


def register(ctx):
    """Register the listening_profile tool and start the background poller."""
    _log("=== register() called ===")
    
    try:
        # 1. Register tool
        _log("Importing schemas and tools...")
        from . import schemas
        from . import tools as profile_tools
        _log("Import OK, registering tool...")
        ctx.register_tool(
            name="listening_profile",
            toolset="hermes-spotify-listening-profile",
            schema=schemas.LISTENING_PROFILE,
            handler=profile_tools.listening_profile,
        )
        _log("Tool registered successfully")
    except Exception as e:
        _log(f"Tool registration FAILED: {type(e).__name__}: {e}")
        _log(traceback.format_exc())
        return

    # 2. Get Config
    try:
        poll_interval_mins = int(os.environ.get("LISTENING_PROFILE_POLL_INTERVAL", "60"))
        poll_interval = max(1, poll_interval_mins) * 60  # Minimum 1 minute, convert to seconds for poller
    except ValueError:
        poll_interval = 3600

    # Stop existing poller if already registered to prevent thread leakage on reload
    if hasattr(profile_tools, "_active_poller") and profile_tools._active_poller:
        try:
            _log("Stopping existing poller thread...")
            profile_tools._active_poller.stop()
        except Exception as e:
            _log(f"Failed to stop old poller: {e}")

    history_dir = _get_history_dir()
    profile_dir = _get_profile_dir()
    
    _log(f"history_dir={history_dir}")
    _log(f"profile_dir={profile_dir}")
    _log(f"poll_interval={poll_interval}s")
    
    # 3. Start Poller
    try:
        from .poller import ListeningPoller
        _log("Poller class imported OK")
        poller = ListeningPoller(
            poll_interval=poll_interval,
            history_dir=history_dir,
            profile_dir=profile_dir,
        )
        poller.start()
        _log("Poller started")
        atexit.register(poller.stop)
        
        # Expose the poller instance on the tools module for on-demand polling
        profile_tools._active_poller = poller
    except Exception as e:
        _log(f"Poller FAILED: {type(e).__name__}: {e}")
        _log(traceback.format_exc())

    _log("=== register() complete ===")
