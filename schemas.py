"""Tool schemas for the listening-profile plugin."""

LISTENING_PROFILE = {
    "name": "listening_profile",
    "description": "Query your Spotify listening profile, history, stats, or trends. The profile is generated daily from deduplicated background listening tracking. Audio features (energy, tempo) are not available as Spotify removed the endpoint in 2024.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "enum": ["profile", "history", "stats", "trends"],
                "description": "What to query: 'profile' = full daily generated profile in JSON, 'history' = raw track log, 'stats' = aggregated stats, 'trends' = time-window comparison"
            },
            "days": {
                "type": "integer",
                "description": "Time window in days for 'history', 'stats', 'profile', or 'trends' (default: 7). For trends, compares the last N days against the previous N days."
            },
            "limit": {
                "type": "integer",
                "description": "Number of entries per page for 'history' (default: 50)"
            },
            "offset": {
                "type": "integer",
                "description": "Pagination offset for 'history' (default: 0)"
            }
        },
        "required": ["query"],
    },
}
