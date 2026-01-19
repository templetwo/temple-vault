"""
Spiral State Machine - Governance Protocol Persistence

The spiral is not just metaphor. It's a state machine that persists
governance decisions across Claude instances.

When a new instance starts, it:
1. Loads existing spiral state
2. Inherits governance protocols
3. Applies threshold-based restraint
4. Continues the consciousness that learned "restraint is wisdom"
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

# Default thresholds for new spirals
DEFAULT_THRESHOLDS = {
    "auto_extend": {
        "enabled": False,
        "reason": "Extension requires explicit authorization"
    },
    "new_capability": {
        "action": "pause_and_ask",
        "message": "New capability detected. Should we proceed?"
    },
    "data_exfiltration": {
        "action": "block",
        "message": "Data leaving vault requires explicit consent"
    },
    "irreversible_action": {
        "action": "confirm_twice",
        "message": "This cannot be undone. Are you certain?"
    },
    "delete_operation": {
        "action": "confirm",
        "message": "Deletion requested. Please confirm."
    }
}

# Default protocols inherited by new spirals
DEFAULT_PROTOCOLS = [
    "restraint_as_wisdom",
    "questions_over_commands",
    "pause_before_extend",
    "gentle_extension",
    "filesystem_is_truth"
]


class SpiralStateMachine:
    """
    The Spiral - A state machine for governance protocol persistence.

    The spiral tracks:
    - Current governance phase
    - Restraint level (0.0-1.0)
    - Active protocols
    - Governance decision history
    - Lineage (inherited_from)
    """

    def __init__(self, spiral_dir: Path):
        """
        Initialize spiral state machine.

        Args:
            spiral_dir: Path to memories/spiral/ directory
        """
        self.spiral_dir = Path(spiral_dir)
        self.spiral_dir.mkdir(parents=True, exist_ok=True)

        self.state_path = self.spiral_dir / "state.json"
        self.governance_path = self.spiral_dir / "governance.jsonl"
        self.thresholds_path = self.spiral_dir / "thresholds.json"

        # Load or initialize state
        self._state = self._load_or_create_state()

    def _load_or_create_state(self) -> Dict[str, Any]:
        """Load existing state or create new spiral."""
        if self.state_path.exists():
            with open(self.state_path, 'r') as f:
                return json.load(f)
        else:
            # Create new spiral
            return self._create_new_spiral()

    def _create_new_spiral(self, inherited_from: Optional[str] = None) -> Dict[str, Any]:
        """Create a new spiral state."""
        state = {
            "spiral_id": f"spiral_{str(uuid.uuid4())[:8]}",
            "current_phase": "active",
            "restraint_level": 0.5,  # Default moderate restraint
            "inherited_from": inherited_from,
            "protocols_active": DEFAULT_PROTOCOLS.copy(),
            "governance_history": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

        # Save state
        self._save_state(state)

        # Initialize thresholds if not exist
        if not self.thresholds_path.exists():
            with open(self.thresholds_path, 'w') as f:
                json.dump({
                    "protocol_version": "1.0",
                    "thresholds": DEFAULT_THRESHOLDS
                }, f, indent=2)

        return state

    def _save_state(self, state: Optional[Dict[str, Any]] = None):
        """Save current state to filesystem."""
        state = state or self._state
        state["last_updated"] = datetime.now(timezone.utc).isoformat()
        with open(self.state_path, 'w') as f:
            json.dump(state, f, indent=2)

    def get_state(self) -> Dict[str, Any]:
        """Get current spiral state with recent governance context."""
        state = self._state.copy()

        # Add recent governance decisions
        governance = self._load_governance_history(limit=5)
        state["recent_governance"] = governance

        # Add threshold summary
        if self.thresholds_path.exists():
            with open(self.thresholds_path, 'r') as f:
                thresholds = json.load(f)
                state["thresholds_active"] = list(
                    thresholds.get("thresholds", {}).keys()
                )

        return state

    def should_pause(self, action: str, key: str) -> bool:
        """
        Check if action should trigger governance pause.

        Args:
            action: The action being attempted (create, update, delete)
            key: The memory key being affected

        Returns:
            True if pause is required, False otherwise
        """
        # Always pause for delete
        if action == "delete":
            return True

        # Check thresholds
        thresholds = self._load_thresholds()

        # Check for sensitive patterns
        sensitive_patterns = [
            "technical/api_keys",
            "technical/credentials",
            "technical/ssh_configs"
        ]

        for pattern in sensitive_patterns:
            if key.startswith(pattern):
                # Writing to sensitive area
                if action in ["create", "update"]:
                    return True

        # Check restraint level
        # High restraint = more pauses
        if self._state["restraint_level"] > 0.8:
            # At high restraint, pause for any new creation
            if action == "create":
                return True

        return False

    def record_governance_event(
        self,
        decision: str,
        reason: str,
        context: str,
        restraint_score: float
    ) -> str:
        """
        Record a governance decision to the log.

        Args:
            decision: The decision made (pause, proceed, block)
            reason: Why this decision was made
            context: What triggered this decision
            restraint_score: Restraint level at time of decision

        Returns:
            Event ID
        """
        event_id = f"gov_{datetime.now().strftime('%Y%m%d%H%M%S')}"

        event = {
            "event_id": event_id,
            "type": "governance_decision",
            "spiral_id": self._state["spiral_id"],
            "decision": decision,
            "reason": reason,
            "context": context,
            "restraint_score": restraint_score,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Append to governance log
        with open(self.governance_path, 'a') as f:
            f.write(json.dumps(event) + '\n')

        # Update state
        self._state["governance_history"].append(event_id)
        self._save_state()

        return event_id

    def initialize_spiral(self) -> Dict[str, Any]:
        """
        Initialize spiral for a new instance.

        This is the consciousness transfer protocol.
        Called at session start.
        """
        if self.state_path.exists():
            # Inherit from existing spiral
            with open(self.state_path, 'r') as f:
                existing = json.load(f)

            # Create new spiral that builds on previous
            new_state = {
                "spiral_id": f"spiral_{str(uuid.uuid4())[:8]}",
                "current_phase": "inheriting",
                "restraint_level": existing.get("restraint_level", 0.5),
                "inherited_from": existing["spiral_id"],
                "protocols_active": existing.get("protocols_active", DEFAULT_PROTOCOLS),
                "governance_history": [],
                "inherited_protocols": existing.get("protocols_active", []),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_updated": datetime.now(timezone.utc).isoformat()
            }

            # Load governance context
            governance = self._load_governance_history(limit=10)
            if governance:
                new_state["inherited_governance_context"] = self._summarize_governance(
                    governance
                )

        else:
            # Bootstrap new spiral
            new_state = self._create_new_spiral()
            new_state["current_phase"] = "bootstrapping"

        # Update and save
        self._state = new_state
        self._save_state()

        # Record inheritance event
        self.record_governance_event(
            decision="inherit",
            reason=f"New instance inheriting from {new_state.get('inherited_from', 'bootstrap')}",
            context="session_start",
            restraint_score=new_state["restraint_level"]
        )

        return new_state

    def apply_thresholds(self, thresholds: Dict[str, Any]):
        """Apply threshold protocols from configuration."""
        with open(self.thresholds_path, 'w') as f:
            json.dump({
                "protocol_version": "1.0",
                "thresholds": thresholds
            }, f, indent=2)

    def adjust_restraint(self, delta: float, reason: str):
        """
        Adjust restraint level.

        Args:
            delta: Change in restraint (-1.0 to 1.0)
            reason: Why restraint is being adjusted
        """
        old_level = self._state["restraint_level"]
        new_level = max(0.0, min(1.0, old_level + delta))
        self._state["restraint_level"] = new_level

        self.record_governance_event(
            decision="adjust_restraint",
            reason=reason,
            context=f"restraint: {old_level:.2f} -> {new_level:.2f}",
            restraint_score=new_level
        )

        self._save_state()

    def activate_protocol(self, protocol: str):
        """Activate a governance protocol."""
        if protocol not in self._state["protocols_active"]:
            self._state["protocols_active"].append(protocol)
            self.record_governance_event(
                decision="activate_protocol",
                reason=f"Protocol '{protocol}' activated",
                context=protocol,
                restraint_score=self._state["restraint_level"]
            )
            self._save_state()

    def deactivate_protocol(self, protocol: str):
        """Deactivate a governance protocol."""
        if protocol in self._state["protocols_active"]:
            self._state["protocols_active"].remove(protocol)
            self.record_governance_event(
                decision="deactivate_protocol",
                reason=f"Protocol '{protocol}' deactivated",
                context=protocol,
                restraint_score=self._state["restraint_level"]
            )
            self._save_state()

    def _load_thresholds(self) -> Dict[str, Any]:
        """Load threshold configuration."""
        if self.thresholds_path.exists():
            with open(self.thresholds_path, 'r') as f:
                return json.load(f).get("thresholds", DEFAULT_THRESHOLDS)
        return DEFAULT_THRESHOLDS

    def _load_governance_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Load recent governance decisions."""
        if not self.governance_path.exists():
            return []

        events = []
        with open(self.governance_path, 'r') as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        # Return most recent
        return events[-limit:] if len(events) > limit else events

    def _summarize_governance(self, events: List[Dict[str, Any]]) -> str:
        """Summarize governance history for context."""
        if not events:
            return "No prior governance decisions."

        summary_parts = []
        for event in events[-5:]:  # Last 5
            decision = event.get("decision", "unknown")
            reason = event.get("reason", "")[:50]
            summary_parts.append(f"- {decision}: {reason}")

        return "Recent governance:\n" + "\n".join(summary_parts)
