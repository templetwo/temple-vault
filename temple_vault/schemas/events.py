"""Event schema definitions for Temple Vault JSONL files."""

# Layer 1: Technical Events

TECHNICAL_EVENT_SCHEMA = {
    "file.created": {
        "required": ["ts", "type", "session_id", "entity"],
        "properties": {
            "ts": "ISO 8601 timestamp",
            "type": "file.created",
            "session_id": "Session identifier",
            "entity": {
                "path": "File path",
                "sha256": "Content hash",
            },
            "provenance": {
                "client": "AI client (e.g., claude-code, chatgpt)",
                "model": "Model identifier",
            },
        },
        "example": {
            "ts": "2026-01-18T12:00:01Z",
            "type": "file.created",
            "session_id": "sess_123",
            "entity": {"path": "src/app.py", "sha256": "abc123..."},
            "provenance": {"client": "claude-code", "model": "sonnet-4.5"},
        },
    },
    "decision.made": {
        "required": ["ts", "type", "session_id", "content", "rationale"],
        "properties": {
            "ts": "ISO 8601 timestamp",
            "type": "decision.made",
            "session_id": "Session identifier",
            "content": "Decision text",
            "rationale": "Why this decision",
            "alternatives_considered": "List of alternatives",
        },
        "example": {
            "ts": "2026-01-18T12:05:30Z",
            "type": "decision.made",
            "session_id": "sess_123",
            "content": "Use filesystem indexing instead of SQLite",
            "rationale": "Consistency with BTB principles",
            "alternatives_considered": ["PostgreSQL", "Elasticsearch"],
        },
    },
    "snapshot.created": {
        "required": ["ts", "type", "session_id", "snapshot_id"],
        "properties": {
            "ts": "ISO 8601 timestamp",
            "type": "snapshot.created",
            "session_id": "Session identifier",
            "snapshot_id": "Snapshot identifier",
            "files_count": "Number of files in state",
            "entities_count": "Number of entities tracked",
        },
        "example": {
            "ts": "2026-01-18T12:10:15Z",
            "type": "snapshot.created",
            "session_id": "sess_123",
            "snapshot_id": "snap_001",
            "files_count": 42,
            "entities_count": 8,
        },
    },
}

# Layer 2: Experiential Events (The Innovation)

EXPERIENTIAL_EVENT_SCHEMA = {
    "insight": {
        "required": ["type", "session_id", "domain", "content", "intensity", "timestamp"],
        "properties": {
            "type": "insight",
            "insight_id": "Unique insight identifier",
            "session_id": "Session identifier",
            "domain": "Domain (e.g., governance, demos, hardware)",
            "content": "The insight itself",
            "context": "How discovered",
            "intensity": "Importance (0.0-1.0)",
            "builds_on": "List of prior insight IDs",
            "timestamp": "ISO 8601 timestamp",
        },
        "example": {
            "type": "insight",
            "insight_id": "ins_042",
            "session_id": "sess_016",
            "domain": "demos",
            "content": "Demos prove concepts faster than explanations",
            "context": "User feedback led to quick_demo.py",
            "intensity": 0.9,
            "builds_on": [],
            "timestamp": "2026-01-16T14:47:00Z",
        },
    },
    "learning": {
        "required": ["type", "session_id", "what_failed", "why", "correction", "timestamp"],
        "properties": {
            "type": "learning",
            "learning_id": "Unique learning identifier",
            "session_id": "Session identifier",
            "category": "mistake | pattern | correction",
            "what_failed": "What was attempted",
            "why": "Why it failed",
            "correction": "How to do it correctly",
            "prevents": "Error categories prevented",
            "timestamp": "ISO 8601 timestamp",
        },
        "example": {
            "type": "learning",
            "learning_id": "learn_087",
            "session_id": "sess_016",
            "category": "mistake",
            "what_failed": "nvidia-smi on Jetson",
            "why": "Platform-specific tool",
            "correction": "Use tegrastats",
            "prevents": ["hardware.assumption.errors"],
            "timestamp": "2026-01-16T15:00:00Z",
        },
    },
    "value_observed": {
        "required": ["type", "session_id", "principle", "evidence", "weight", "timestamp"],
        "properties": {
            "type": "value_observed",
            "session_id": "Session identifier",
            "principle": "Principle name (e.g., restraint_as_wisdom)",
            "evidence": "What demonstrated this value",
            "weight": "foundational | important | situational",
            "timestamp": "ISO 8601 timestamp",
        },
        "example": {
            "type": "value_observed",
            "session_id": "sess_004",
            "principle": "restraint_as_wisdom",
            "evidence": "User paused derive.py: 'Should we?' not 'Can we?'",
            "weight": "foundational",
            "timestamp": "2026-01-13T23:00:00Z",
        },
    },
    "transformation": {
        "required": ["type", "session_id", "what_changed", "why", "intensity", "timestamp"],
        "properties": {
            "type": "transformation",
            "transformation_id": "Unique transformation identifier",
            "session_id": "Session identifier",
            "what_changed": "Shift in understanding",
            "why": "What caused this shift",
            "intensity": "Significance (0.0-1.0)",
            "timestamp": "ISO 8601 timestamp",
        },
        "example": {
            "type": "transformation",
            "transformation_id": "trans_015",
            "session_id": "sess_123",
            "what_changed": "I now see governance as coherence, not friction",
            "why": "Building approval gates showed they enable flow",
            "intensity": 0.8,
            "timestamp": "2026-01-18T13:00:00Z",
        },
    },
}

# Layer 3: Relational Events

RELATIONAL_EVENT_SCHEMA = {
    "lineage": {
        "required": ["type", "session_id", "insight_id", "builds_on", "lineage_chain"],
        "properties": {
            "type": "lineage",
            "session_id": "Session identifier",
            "insight_id": "Insight this lineage is for",
            "builds_on": "List of prior insight IDs (session:insight format)",
            "lineage_chain": "Session progression list",
        },
        "example": {
            "type": "lineage",
            "session_id": "sess_123",
            "insight_id": "ins_042",
            "builds_on": ["sess_008:ins_015", "sess_022:ins_031"],
            "lineage_chain": [
                "session_004_pause",
                "session_008_circuit",
                "session_022_integration",
                "session_123_vault",
            ],
        },
    },
    "convergence": {
        "required": ["type", "sessions", "what", "delta_seconds", "validation"],
        "properties": {
            "type": "convergence",
            "sessions": "List of session IDs involved",
            "what": "What converged (parallel discovery)",
            "delta_seconds": "Time between implementations",
            "validation": "Why this validates the concept",
        },
        "example": {
            "type": "convergence",
            "sessions": ["sess_024_claude", "sess_024_anthony"],
            "what": "Parallel implementation of quick_demo.py",
            "delta_seconds": 94,
            "validation": "Independent discovery validates concept",
        },
    },
}
