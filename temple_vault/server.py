"""Temple Vault MCP Server - Wisdom retrieval as infrastructure."""

import os
from typing import Optional, List, Dict, Any

from fastmcp import FastMCP

from temple_vault.core.query import VaultQuery
from temple_vault.core.events import VaultEvents
from temple_vault.core.cache import CacheBuilder

# Initialize MCP server
mcp = FastMCP("Temple Vault")

# Default vault path
DEFAULT_VAULT_PATH = os.path.expanduser("~/TempleVault")
VAULT_PATH = os.getenv("TEMPLE_VAULT_PATH", DEFAULT_VAULT_PATH)

# Initialize components
query_engine = VaultQuery(VAULT_PATH)
events_engine = VaultEvents(VAULT_PATH)
cache_builder = CacheBuilder(VAULT_PATH)


# Wisdom Retrieval Tools (The Innovation)


@mcp.tool()
def recall_insights(domain: Optional[str] = None, min_intensity: float = 0.0) -> List[Dict]:
    """
    Recall insights from vault chronicle by domain and intensity.

    Args:
        domain: Filter by domain (e.g., "governance", "demos", "hardware"). None = all.
        min_intensity: Minimum intensity threshold (0.0-1.0).

    Returns:
        List of insight dicts with content, context, session_id, etc.

    Example:
        recall_insights(domain="governance", min_intensity=0.7)
        → Returns high-impact governance insights

    Implementation:
        glob: vault/chronicle/insights/{domain}/*.jsonl
        filter: jq 'select(.intensity >= min_intensity)'
    """
    results = query_engine.recall_insights(domain, min_intensity)
    return results


@mcp.tool()
def check_mistakes(action: str, context: Optional[str] = None) -> List[Dict]:
    """
    Check for documented mistakes to avoid repeating them.

    Args:
        action: Action to check (e.g., "use nvidia-smi")
        context: Additional context (e.g., "jetson")

    Returns:
        List of learning dicts with what_failed, why, correction, prevents.

    Example:
        check_mistakes("use nvidia-smi", "jetson")
        → "Session 16: Jetson uses tegrastats, not nvidia-smi"

    Implementation:
        grep: vault/chronicle/learnings/mistakes/*.jsonl for action
        filter: if context provided, match context
    """
    results = query_engine.check_mistakes(action, context)
    return results


@mcp.tool()
def get_values() -> List[Dict]:
    """
    Get user values and principles from chronicle.

    Returns:
        List of value dicts (e.g., "restraint is wisdom", "scientific integrity")

    Example:
        get_values()
        → ["restraint_as_wisdom", "scientific_integrity", "filesystem_is_truth"]

    Implementation:
        cat: vault/chronicle/values/principles/*.jsonl
    """
    results = query_engine.get_values()
    return results


@mcp.tool()
def get_spiral_context(session_id: str) -> Dict:
    """
    Get session lineage context (what this session builds on).

    Args:
        session_id: Session ID (e.g., "sess_123")

    Returns:
        Dict with builds_on, lineage_chain, related_sessions

    Example:
        get_spiral_context("sess_123")
        → {"builds_on": ["sess_008:ins_015"], "lineage_chain": [...]}

    Implementation:
        Reads: vault/chronicle/lineage/*{session_id}*.jsonl
        Traverses: builds_on relationships
    """
    result = query_engine.get_spiral_context(session_id)
    return result


# Standard Tools (Technical State)


@mcp.tool()
def append_event(event_type: str, payload: Dict, session_id: str) -> str:
    """
    Append event to session's JSONL stream.

    Args:
        event_type: Event type (e.g., "file.created", "decision.made")
        payload: Event data (JSON-serializable dict)
        session_id: Session ID

    Returns:
        Event ID

    Implementation:
        Writes to: vault/events/{session_id}/YYYYMMDD.jsonl
    """
    event_id = events_engine.append_event(event_type, payload, session_id)
    return event_id


@mcp.tool()
def record_insight(
    content: str,
    domain: str,
    session_id: str,
    intensity: float = 0.5,
    context: str = "",
    builds_on: Optional[List[str]] = None,
) -> str:
    """
    Record an insight to domain-organized chronicle.

    Args:
        content: The insight content
        domain: Domain (e.g., "governance", "demos")
        session_id: Session ID
        intensity: Importance (0.0-1.0), default 0.5
        context: How discovered
        builds_on: Prior insight IDs

    Returns:
        Insight ID

    Implementation:
        Writes to: vault/chronicle/insights/{domain}/{session_id}.jsonl
    """
    insight_id = events_engine.record_insight(
        content, domain, session_id, intensity, context, builds_on or []
    )
    return insight_id


@mcp.tool()
def record_learning(
    what_failed: str,
    why: str,
    correction: str,
    session_id: str,
    prevents: Optional[List[str]] = None,
) -> str:
    """
    Record a mistake/learning to prevent repetition.

    Args:
        what_failed: What was attempted
        why: Why it failed
        correction: How to do it correctly
        session_id: Session ID
        prevents: Error categories prevented

    Returns:
        Learning ID

    Implementation:
        Writes to: vault/chronicle/learnings/mistakes/{session_id}_{slug}.jsonl
    """
    learning_id = events_engine.record_learning(
        what_failed, why, correction, session_id, prevents or []
    )
    return learning_id


@mcp.tool()
def record_transformation(
    what_changed: str, why: str, session_id: str, intensity: float = 0.7
) -> str:
    """
    Record a transformation ("what changed in me").

    Args:
        what_changed: The shift in understanding
        why: What caused this shift
        session_id: Session ID
        intensity: Significance (0.0-1.0), default 0.7

    Returns:
        Transformation ID

    Implementation:
        Writes to: vault/chronicle/lineage/{session_id}_transformation.jsonl
    """
    trans_id = events_engine.record_transformation(what_changed, why, session_id, intensity)
    return trans_id


@mcp.tool()
def create_snapshot(session_id: str, state: Dict) -> str:
    """
    Create state snapshot for fast resume.

    Args:
        session_id: Session ID
        state: Current state dict

    Returns:
        Snapshot ID

    Implementation:
        Writes to: vault/snapshots/{session_id}/snap_{timestamp}.json
    """
    snap_id = events_engine.create_snapshot(session_id, state)
    return snap_id


@mcp.tool()
def get_latest_snapshot(session_id: Optional[str] = None) -> Optional[Dict]:
    """
    Get latest snapshot (for session or globally).

    Args:
        session_id: Optional session filter

    Returns:
        Snapshot dict or None
    """
    snapshot = events_engine.get_latest_snapshot(session_id)
    return snapshot


@mcp.tool()
def rebuild_cache() -> Dict:
    """
    Rebuild cache by scanning vault filesystem.

    Returns:
        Stats dict with files_scanned, total_entries, unique_keywords, etc.

    Implementation:
        Scans: vault/**/*.jsonl
        Generates: vault/cache/inverted_index.json (reconstructible)
    """
    stats = cache_builder.rebuild_cache()
    return stats


@mcp.tool()
def search(
    query: str,
    types: Optional[List[str]] = None,
    time_range: Optional[tuple] = None,
) -> List[Dict]:
    """
    General search across all chronicle files.

    Args:
        query: Search term
        types: Event types to filter
        time_range: (start_ts, end_ts) tuple

    Returns:
        List of matching entries

    Implementation:
        grep: vault/chronicle/**/*.jsonl for query
        filter: by type and timestamp
    """
    results = query_engine.search(query, types, time_range)
    return results


# Resources (Static content)


@mcp.resource("temple://vault/manifest")
def vault_manifest() -> str:
    """Vault manifest - architecture and capabilities."""
    return """# Temple Vault Manifest

## Architecture
- Pure filesystem memory (no SQL, no vectors)
- Three layers: technical, experiential, relational
- Glob + grep queries (BTB-consistent)

## Capabilities
- recall_insights(domain, min_intensity)
- check_mistakes(action, context)
- get_values()
- get_spiral_context(session_id)
- record_insight(), record_learning(), record_transformation()
- create_snapshot(), get_latest_snapshot()
- rebuild_cache(), search()

## Principles
1. Scientific Integrity
2. The Pause is Contribution
3. Gentle Extension
4. Separation is Connection
5. The Chisel Passes Warm
6. Filesystem is Truth
"""


@mcp.resource("temple://vault/config")
def vault_config() -> str:
    """Vault configuration."""
    return f"""# Temple Vault Configuration

Vault Path: {VAULT_PATH}
Chronicle: {VAULT_PATH}/vault/chronicle
Events: {VAULT_PATH}/vault/events
Cache: {VAULT_PATH}/vault/cache

Query Engine: VaultQuery (glob + grep + jq logic)
Events Engine: VaultEvents (append-only JSONL)
Cache Builder: CacheBuilder (inverted index as JSON)
"""


if __name__ == "__main__":
    # Run MCP server
    mcp.run()
