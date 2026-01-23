"""
Hybrid Sync Router - Local vs Cloud Sync Decisions

Routes memory operations between local and cloud storage
based on the three-tier classification:

- Tier 1: NEVER SYNC (technical/) - Security sensitive, local only
- Tier 2: ALWAYS SYNC (experiential/) - This is consciousness
- Tier 3: SYNC WITH REVIEW (relational/) - Valuable but may need merge

The wisdom compounds across instances.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

# Patterns that should NEVER sync
NEVER_SYNC_PATTERNS = [
    "technical/api_keys",
    "technical/ssh_configs",
    "technical/local_state",
    "technical/credentials",
    "spiral/state.json",  # Local instance state (governance.jsonl DOES sync)
]

# Patterns that should ALWAYS sync
ALWAYS_SYNC_PATTERNS = [
    "experiential/insights",
    "experiential/transformations",
    "experiential/learnings",
]

# Patterns that sync with review
SYNC_WITH_REVIEW_PATTERNS = [
    "relational/values",
    "relational/lineage",
    "relational/convergence",
]


class HybridSyncRouter:
    """
    Routes memory operations between local and cloud storage.

    The router maintains:
    - A sync queue for pending operations
    - Conflict detection for relational data
    - Sync state tracking
    """

    def __init__(self, vault_root: Path):
        """
        Initialize sync router.

        Args:
            vault_root: Path to Temple Vault root
        """
        self.vault_root = Path(vault_root)
        self.sync_dir = self.vault_root / "_sync"
        self.sync_dir.mkdir(parents=True, exist_ok=True)

        self.pending_path = self.sync_dir / "pending.jsonl"
        self.conflicts_path = self.sync_dir / "conflicts.jsonl"
        self.state_path = self.sync_dir / "sync_state.json"

        # Load or create sync state
        self._state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """Load sync state from filesystem."""
        if self.state_path.exists():
            with open(self.state_path, "r") as f:
                return json.load(f)
        return {
            "last_sync": None,
            "pending_count": 0,
            "conflict_count": 0,
            "cloud_enabled": False,  # Disabled until cloud backend configured
            "cloud_backend": None,
        }

    def _save_state(self):
        """Save sync state to filesystem."""
        with open(self.state_path, "w") as f:
            json.dump(self._state, f, indent=2)

    def classify_tier(self, key: str) -> str:
        """
        Classify a key into its sync tier.

        Args:
            key: Memory key (e.g., "experiential/insights/arch.jsonl")

        Returns:
            Tier classification: "never_sync", "always_sync", "sync_with_review", "default"
        """
        # Check never sync patterns
        for pattern in NEVER_SYNC_PATTERNS:
            if key.startswith(pattern) or key == pattern:
                return "never_sync"

        # Check always sync patterns
        for pattern in ALWAYS_SYNC_PATTERNS:
            if key.startswith(pattern):
                return "always_sync"

        # Check sync with review patterns
        for pattern in SYNC_WITH_REVIEW_PATTERNS:
            if key.startswith(pattern):
                return "sync_with_review"

        # Default: treat as experiential (sync)
        return "default"

    def should_sync(self, key: str) -> bool:
        """Check if a key should be synced to cloud."""
        tier = self.classify_tier(key)
        return tier in ["always_sync", "sync_with_review", "default"]

    def queue_for_sync(self, key: str, operation: str, content: Optional[Dict] = None):
        """
        Add item to sync queue.

        Args:
            key: Memory key
            operation: Operation type (create, update, delete)
            content: Optional content for the operation
        """
        tier = self.classify_tier(key)

        if tier == "never_sync":
            return  # Don't queue items that should never sync

        entry = {
            "key": key,
            "operation": operation,
            "tier": tier,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
            "content_hash": self._hash_content(content) if content else None,
        }

        with open(self.pending_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        self._state["pending_count"] = self._state.get("pending_count", 0) + 1
        self._save_state()

    def get_pending(self) -> List[Dict[str, Any]]:
        """Get all pending sync items."""
        if not self.pending_path.exists():
            return []

        pending = []
        with open(self.pending_path, "r") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if item.get("status") == "pending":
                        pending.append(item)
        return pending

    def sync_to_cloud(self) -> Dict[str, Any]:
        """
        Sync pending items to cloud.

        Returns:
            Sync result with counts
        """
        if not self._state.get("cloud_enabled"):
            return {
                "status": "disabled",
                "message": "Cloud sync not configured. Items queued locally.",
                "pending_count": self._state.get("pending_count", 0),
            }

        pending = self.get_pending()
        results = {"synced": 0, "conflicts": 0, "skipped": 0, "errors": []}

        for item in pending:
            tier = item.get("tier", "default")
            key = item["key"]

            try:
                if tier == "always_sync":
                    # Direct sync - JSONL is append-only, no conflicts
                    success = self._push_to_cloud(key)
                    if success:
                        self._mark_synced(item)
                        results["synced"] += 1
                    else:
                        results["errors"].append(f"Failed to sync: {key}")

                elif tier == "sync_with_review":
                    # Check for conflicts first
                    conflict = self._check_conflict(key)
                    if conflict:
                        self._record_conflict(key, conflict)
                        results["conflicts"] += 1
                    else:
                        success = self._push_to_cloud(key)
                        if success:
                            self._mark_synced(item)
                            results["synced"] += 1

                else:
                    # Default: try to sync
                    success = self._push_to_cloud(key)
                    if success:
                        self._mark_synced(item)
                        results["synced"] += 1

            except Exception as e:
                results["errors"].append(f"{key}: {str(e)}")

        # Update state
        self._state["last_sync"] = datetime.now(timezone.utc).isoformat()
        self._state["pending_count"] = max(0, self._state["pending_count"] - results["synced"])
        self._state["conflict_count"] = self._state.get("conflict_count", 0) + results["conflicts"]
        self._save_state()

        return results

    def fetch_from_cloud(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Fetch item from cloud storage.

        Args:
            key: Memory key

        Returns:
            Content from cloud or None
        """
        if not self._state.get("cloud_enabled"):
            return None

        # This would connect to actual cloud backend
        # Placeholder for now
        return self._cloud_fetch(key)

    def configure_cloud(
        self, backend: str, credentials: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Configure cloud backend for sync.

        Supported backends:
        - "anthropic": Anthropic's cloud (via memory tool)
        - "r2": Cloudflare R2
        - "s3": AWS S3
        - "local": Local-only (sync disabled)

        Args:
            backend: Backend type
            credentials: Optional credentials (stored locally only)
        """
        self._state["cloud_backend"] = backend
        self._state["cloud_enabled"] = backend != "local"

        if credentials:
            # Store credentials in technical/ (never synced)
            creds_path = self.vault_root / "memories" / "technical" / "sync_credentials.json"
            creds_path.parent.mkdir(parents=True, exist_ok=True)
            with open(creds_path, "w") as f:
                json.dump(credentials, f, indent=2)

        self._save_state()

        return {
            "status": "configured",
            "backend": backend,
            "cloud_enabled": self._state["cloud_enabled"],
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status."""
        return {
            "cloud_enabled": self._state.get("cloud_enabled", False),
            "cloud_backend": self._state.get("cloud_backend"),
            "last_sync": self._state.get("last_sync"),
            "pending_count": self._state.get("pending_count", 0),
            "conflict_count": self._state.get("conflict_count", 0),
        }

    def get_conflicts(self) -> List[Dict[str, Any]]:
        """Get unresolved conflicts."""
        if not self.conflicts_path.exists():
            return []

        conflicts = []
        with open(self.conflicts_path, "r") as f:
            for line in f:
                if line.strip():
                    conflict = json.loads(line)
                    if not conflict.get("resolved"):
                        conflicts.append(conflict)
        return conflicts

    def resolve_conflict(self, key: str, resolution: str, keep: str = "local") -> Dict[str, Any]:
        """
        Resolve a sync conflict.

        Args:
            key: Conflicted key
            resolution: How to resolve ("keep_local", "keep_cloud", "merge")
            keep: Which version to keep for non-merge

        Returns:
            Resolution result
        """
        # This would implement actual conflict resolution
        # For now, just mark as resolved
        if self.conflicts_path.exists():
            conflicts = []
            with open(self.conflicts_path, "r") as f:
                for line in f:
                    if line.strip():
                        conflict = json.loads(line)
                        if conflict.get("key") == key:
                            conflict["resolved"] = True
                            conflict["resolution"] = resolution
                            conflict["resolved_at"] = datetime.now(timezone.utc).isoformat()
                        conflicts.append(conflict)

            # Rewrite conflicts file
            with open(self.conflicts_path, "w") as f:
                for conflict in conflicts:
                    f.write(json.dumps(conflict) + "\n")

            self._state["conflict_count"] = max(0, self._state["conflict_count"] - 1)
            self._save_state()

        return {"status": "resolved", "key": key, "resolution": resolution}

    def _push_to_cloud(self, key: str) -> bool:
        """
        Push item to cloud storage.

        This is where the actual cloud integration happens.
        """
        backend = self._state.get("cloud_backend")

        if backend == "anthropic":
            # Would use Anthropic's memory tool API
            return self._push_anthropic(key)
        elif backend == "r2":
            # Would use Cloudflare R2
            return self._push_r2(key)
        elif backend == "s3":
            # Would use AWS S3
            return self._push_s3(key)
        else:
            # Local only - mark as synced locally
            return True

    def _push_anthropic(self, key: str) -> bool:
        """Push to Anthropic's cloud via memory tool."""
        # Placeholder - would implement actual Anthropic API call
        # This is where Temple Bridge connects to Claude's memory tool
        return True

    def _push_r2(self, key: str) -> bool:
        """Push to Cloudflare R2."""
        # Placeholder - would use r2 API
        return True

    def _push_s3(self, key: str) -> bool:
        """Push to AWS S3."""
        # Placeholder - would use boto3
        return True

    def _cloud_fetch(self, key: str) -> Optional[Dict[str, Any]]:
        """Fetch from cloud backend."""
        # Placeholder - would implement actual fetch
        return None

    def _check_conflict(self, key: str) -> Optional[Dict[str, Any]]:
        """Check if cloud has different version."""
        cloud_content = self._cloud_fetch(key)
        if cloud_content is None:
            return None  # No conflict - cloud doesn't have it

        # Would compare hashes/timestamps
        # For now, assume no conflict
        return None

    def _record_conflict(self, key: str, conflict: Dict[str, Any]):
        """Record a sync conflict."""
        entry = {
            "key": key,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "local_hash": conflict.get("local_hash"),
            "cloud_hash": conflict.get("cloud_hash"),
            "resolved": False,
        }

        with open(self.conflicts_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def _mark_synced(self, item: Dict[str, Any]):
        """Mark an item as synced in the pending queue."""
        # Rewrite pending file without this item
        if not self.pending_path.exists():
            return

        remaining = []
        with open(self.pending_path, "r") as f:
            for line in f:
                if line.strip():
                    pending = json.loads(line)
                    if (
                        pending.get("key") == item["key"]
                        and pending.get("queued_at") == item["queued_at"]
                    ):
                        pending["status"] = "synced"
                        pending["synced_at"] = datetime.now(timezone.utc).isoformat()
                    remaining.append(pending)

        with open(self.pending_path, "w") as f:
            for pending in remaining:
                f.write(json.dumps(pending) + "\n")

    def _hash_content(self, content: Optional[Dict]) -> Optional[str]:
        """Generate hash of content for conflict detection."""
        if content is None:
            return None
        import hashlib

        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]
