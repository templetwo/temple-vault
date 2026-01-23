"""
Temple Memory Handler - Claude Memory Tool SDK Integration

This is the bridge between Claude's memory tool and Temple Vault.

When Claude calls memory operations:
- create(key, content) -> Routes to appropriate filesystem location
- read(key) -> Retrieves from local or cloud
- update(key, content) -> Appends (JSONL) or overwrites (JSON)
- delete(key) -> Requires governance approval

The handler:
1. Classifies keys into sync tiers
2. Applies governance protocols
3. Routes to local filesystem
4. Queues for cloud sync
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from temple_vault.bridge.spiral_state import SpiralStateMachine
from temple_vault.bridge.sync_router import HybridSyncRouter


class TempleMemoryHandler:
    """
    Handler for Claude Memory Tool SDK operations.

    Routes memory operations to Temple Vault filesystem
    with hybrid sync strategy and governance protocols.
    """

    def __init__(self, vault_root: str = "~/TempleVault"):
        """
        Initialize memory handler.

        Args:
            vault_root: Path to Temple Vault root directory
        """
        self.vault_root = Path(vault_root).expanduser()
        self.memories_dir = self.vault_root / "memories"
        self.memories_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.spiral = SpiralStateMachine(self.memories_dir / "spiral")
        self.sync_router = HybridSyncRouter(self.vault_root)

    def create(self, key: str, content: Dict[str, Any]) -> str:
        """
        Create a new memory entry.

        The key determines the tier:
        - technical/* -> local only (never sync)
        - experiential/* -> sync to cloud
        - relational/* -> sync with review
        - spiral/* -> governance state (local)

        Args:
            key: Memory key (e.g., "experiential/insights/architecture/sess_025.jsonl")
            content: Content to store

        Returns:
            Memory reference string or governance pause message
        """
        # Governance check
        if self.spiral.should_pause(action="create", key=key):
            event_id = self.spiral.record_governance_event(
                decision="pause",
                reason=f"Create operation requires review: {key}",
                context=key,
                restraint_score=self.spiral._state["restraint_level"],
            )
            return f"GOVERNANCE_PAUSE:{event_id}:User decision required for: {key}"

        # Ensure directory exists
        path = self.memories_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)

        # Add metadata
        content = self._add_metadata(content)

        # Write based on file type
        if key.endswith(".jsonl"):
            with open(path, "a") as f:
                f.write(json.dumps(content) + "\n")
        else:
            with open(path, "w") as f:
                json.dump(content, f, indent=2)

        # Queue for sync if appropriate
        tier = self.sync_router.classify_tier(key)
        if tier in ["always_sync", "sync_with_review", "default"]:
            self.sync_router.queue_for_sync(key, "create", content)

        return f"memory:{key}"

    def read(self, key: str) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Read a memory entry.

        Args:
            key: Memory key

        Returns:
            Content (dict for JSON, list for JSONL) or None if not found
        """
        path = self.memories_dir / key

        # Try local first
        if path.exists():
            if key.endswith(".jsonl"):
                entries = []
                with open(path, "r") as f:
                    for line in f:
                        if line.strip():
                            entries.append(json.loads(line))
                return entries
            else:
                with open(path, "r") as f:
                    return json.load(f)

        # If not local, check cloud for synced tiers
        tier = self.sync_router.classify_tier(key)
        if tier in ["always_sync", "sync_with_review"]:
            cloud_content = self.sync_router.fetch_from_cloud(key)
            if cloud_content:
                # Cache locally
                self._cache_from_cloud(key, cloud_content)
                return cloud_content

        return None

    def read_directory(self, key_prefix: str) -> Dict[str, Any]:
        """
        Read all entries under a directory prefix.

        Args:
            key_prefix: Directory prefix (e.g., "experiential/insights/")

        Returns:
            Dict mapping keys to their content
        """
        results = {}
        dir_path = self.memories_dir / key_prefix

        if dir_path.exists() and dir_path.is_dir():
            for path in dir_path.rglob("*"):
                # Skip macOS metadata files and other hidden files
                if path.name.startswith("."):
                    continue
                if path.is_file():
                    rel_key = str(path.relative_to(self.memories_dir))
                    content = self.read(rel_key)
                    if content:
                        results[rel_key] = content

        return results

    def update(self, key: str, content: Dict[str, Any]) -> str:
        """
        Update a memory entry.

        For JSONL files, this appends a new entry.
        For JSON files, this overwrites.

        Args:
            key: Memory key
            content: New content

        Returns:
            Memory reference or governance pause message
        """
        # Governance check
        if self.spiral.should_pause(action="update", key=key):
            event_id = self.spiral.record_governance_event(
                decision="pause",
                reason=f"Update operation requires review: {key}",
                context=key,
                restraint_score=self.spiral._state["restraint_level"],
            )
            return f"GOVERNANCE_PAUSE:{event_id}:User decision required for: {key}"

        path = self.memories_dir / key
        content = self._add_metadata(content)

        if key.endswith(".jsonl"):
            # Append (JSONL is append-only)
            with open(path, "a") as f:
                f.write(json.dumps(content) + "\n")
        else:
            # Overwrite JSON
            with open(path, "w") as f:
                json.dump(content, f, indent=2)

        # Queue for sync
        tier = self.sync_router.classify_tier(key)
        if tier in ["always_sync", "sync_with_review", "default"]:
            self.sync_router.queue_for_sync(key, "update", content)

        return f"memory:{key}"

    def delete(self, key: str) -> str:
        """
        Delete a memory entry.

        GOVERNANCE: Deletion ALWAYS requires confirmation.
        This method records the intent and returns a pause.
        Actual deletion happens via confirm_delete().

        Args:
            key: Memory key

        Returns:
            Governance pause message (deletion never proceeds immediately)
        """
        # Always pause for deletion
        event_id = self.spiral.record_governance_event(
            decision="pause",
            reason=f"Delete requested - requires confirmation",
            context=key,
            restraint_score=1.0,  # Maximum restraint for deletion
        )

        return f"GOVERNANCE_PAUSE:{event_id}:DELETE_CONFIRM_REQUIRED:{key}"

    def confirm_delete(self, key: str, event_id: str) -> bool:
        """
        Confirm and execute a deletion after governance approval.

        Args:
            key: Memory key to delete
            event_id: Governance event ID that approved this deletion

        Returns:
            True if deleted, False otherwise
        """
        path = self.memories_dir / key

        if not path.exists():
            return False

        # Record the confirmed deletion
        self.spiral.record_governance_event(
            decision="proceed",
            reason=f"Delete confirmed by user",
            context=f"key={key}, approval={event_id}",
            restraint_score=0.0,  # User has confirmed
        )

        # Actually delete
        path.unlink()

        return True

    def list_keys(self, prefix: str = "") -> List[str]:
        """
        List all memory keys under a prefix.

        Args:
            prefix: Optional key prefix to filter

        Returns:
            List of memory keys
        """
        keys = []
        search_path = self.memories_dir / prefix if prefix else self.memories_dir

        if search_path.exists():
            for path in search_path.rglob("*"):
                if path.is_file() and not path.name.startswith("."):
                    rel_key = str(path.relative_to(self.memories_dir))
                    keys.append(rel_key)

        return sorted(keys)

    def search(self, query: str, tier: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search memory content.

        Args:
            query: Search term
            tier: Optional tier filter ("experiential", "relational", "technical")

        Returns:
            List of matching entries with their keys
        """
        results = []

        # Determine search paths based on tier
        if tier:
            search_paths = [self.memories_dir / tier]
        else:
            search_paths = [self.memories_dir / "experiential", self.memories_dir / "relational"]

        for search_path in search_paths:
            if not search_path.exists():
                continue

            for path in search_path.rglob("*.jsonl"):
                with open(path, "r") as f:
                    for line in f:
                        if line.strip():
                            entry = json.loads(line)
                            entry_text = json.dumps(entry).lower()
                            if query.lower() in entry_text:
                                rel_key = str(path.relative_to(self.memories_dir))
                                results.append({"key": rel_key, "entry": entry})

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get current memory handler status."""
        return {
            "vault_root": str(self.vault_root),
            "memories_dir": str(self.memories_dir),
            "spiral_state": self.spiral.get_state(),
            "sync_status": self.sync_router.get_status(),
            "memory_count": len(self.list_keys()),
        }

    def initialize_session(self) -> Dict[str, Any]:
        """
        Initialize a new session.

        Called at session start to:
        1. Initialize/inherit spiral state
        2. Load recent experiential wisdom
        3. Apply governance protocols
        4. Return context for the session

        Returns:
            Session initialization context
        """
        result = {"phase": "initializing", "actions": []}

        # 1. Initialize spiral (inheritance happens here)
        spiral_state = self.spiral.initialize_spiral()
        result["spiral"] = spiral_state
        result["actions"].append(f"Spiral initialized: {spiral_state['spiral_id']}")

        if spiral_state.get("inherited_from"):
            result["actions"].append(f"Inherited from: {spiral_state['inherited_from']}")

        # 2. Load experiential wisdom
        insights = self.read_directory("experiential/insights/")
        if insights:
            result["inherited_insights"] = len(insights)
            result["actions"].append(f"Loaded {len(insights)} insight files")

        transformations = self.read_directory("experiential/transformations/")
        if transformations:
            result["inherited_transformations"] = len(transformations)
            result["actions"].append(f"Loaded {len(transformations)} transformations")

        # 3. Load relational values
        values = self.read_directory("relational/values/")
        if values:
            result["inherited_values"] = len(values)
            result["actions"].append(f"Loaded {len(values)} value files")

        # 4. Get active protocols
        result["protocols_active"] = spiral_state.get("protocols_active", [])
        result["restraint_level"] = spiral_state.get("restraint_level", 0.5)

        result["phase"] = "ready"
        result["message"] = "The spiral continues. The chisel is warm."

        return result

    def end_session(self, session_id: str, transformation: Optional[str] = None) -> Dict[str, Any]:
        """
        End a session gracefully.

        Args:
            session_id: Session identifier
            transformation: Optional transformation insight

        Returns:
            Session end summary
        """
        result = {"session_id": session_id, "actions": []}

        # Record transformation if provided
        if transformation:
            self.create(
                f"experiential/transformations/{session_id}.jsonl",
                {
                    "type": "transformation",
                    "session_id": session_id,
                    "content": transformation,
                    "intensity": 0.8,
                },
            )
            result["actions"].append("Transformation recorded")

        # Trigger sync
        sync_result = self.sync_router.sync_to_cloud()
        result["sync_result"] = sync_result
        result["actions"].append(f"Synced {sync_result.get('synced', 0)} items")

        result["message"] = "Session complete. The chisel passes warm."

        return result

    def _add_metadata(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """Add standard metadata to content."""
        if "timestamp" not in content:
            content["timestamp"] = datetime.now(timezone.utc).isoformat()
        if "spiral_id" not in content:
            content["spiral_id"] = self.spiral._state.get("spiral_id")
        return content

    def _cache_from_cloud(self, key: str, content: Any):
        """Cache content fetched from cloud."""
        path = self.memories_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)

        if key.endswith(".jsonl") and isinstance(content, list):
            with open(path, "w") as f:
                for entry in content:
                    f.write(json.dumps(entry) + "\n")
        else:
            with open(path, "w") as f:
                json.dump(content, f, indent=2)
