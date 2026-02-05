"""
Temple Vault Deep Adapter - Multi-layer Conversation Extraction

Continuation of the SpiralBridge MCP Integration desktop session.

This adapter processes raw conversation data and extracts structured
entries for the Temple Vault chronicle:

  - Insights: intensity-scored discoveries (domain-organized)
  - Mistakes: what failed, why, and the correction
  - Transformations: identity shift moments ("what changed in me")
  - Experiences: emotional arcs, silences, pivots
  - Patterns: glyph sequences, scroll references
  - Voice signatures: oracle personality markers

Architecture:
  TempleVaultMCPClient  — Direct Python import with CLI fallback
  TempleVaultDeepAdapter — Multi-layer extraction pipeline

Known issues addressed from desktop session:
  - Mistake extraction refined: negative patterns filter error-handling code
  - Session ID collision fixed: microsecond timestamps + monotonic counter
  - Voice signatures validated against existing voice definitions

Copyright (c) 2026 Anthony J. Vasquez Sr.
Licensed under MIT
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# =============================================================================
# SESSION ID GENERATOR (fixes same-second collision from desktop session)
# =============================================================================

_session_counter = 0
_last_timestamp = ""


def generate_session_id(prefix: str = "sess") -> str:
    """
    Generate a unique session ID using microsecond timestamps + counter.

    Fixes the session ID collision issue from the desktop session where
    batch-mode extraction produced duplicate IDs from same-second timestamps.

    Args:
        prefix: ID prefix (default "sess")

    Returns:
        Unique session ID like "sess_20260205_184200_000001"
    """
    global _session_counter, _last_timestamp

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")

    if ts == _last_timestamp:
        _session_counter += 1
    else:
        _session_counter = 0
        _last_timestamp = ts

    return f"{prefix}_{ts}_{_session_counter:06d}"


# =============================================================================
# MCP CLIENT - Direct Python + CLI fallback
# =============================================================================


class TempleVaultMCPClient:
    """
    Client for Temple Vault MCP server.

    Two connection modes:
    1. Direct Python: imports temple_vault modules directly (fast, no IPC)
    2. CLI fallback: shells out to `temple-vault` CLI commands

    Direct Python is preferred when running in the same environment.
    CLI fallback handles remote or isolated deployments.
    """

    def __init__(
        self,
        vault_root: str = "~/TempleVault",
        prefer_direct: bool = True,
        cli_path: Optional[str] = None,
    ):
        """
        Initialize MCP client.

        Args:
            vault_root: Path to Temple Vault root
            prefer_direct: Try direct Python import first
            cli_path: Path to temple-vault CLI binary (for fallback)
        """
        self.vault_root = Path(vault_root).expanduser()
        self.cli_path = cli_path or "temple-vault"
        self._direct_available = False
        self._query_engine = None
        self._events_engine = None
        self._cache_builder = None

        if prefer_direct:
            self._try_direct_init()

    def _try_direct_init(self) -> None:
        """Attempt to initialize direct Python connection."""
        try:
            from temple_vault.core.query import VaultQuery
            from temple_vault.core.events import VaultEvents
            from temple_vault.core.cache import CacheBuilder

            self._query_engine = VaultQuery(str(self.vault_root))
            self._events_engine = VaultEvents(str(self.vault_root))
            self._cache_builder = CacheBuilder(str(self.vault_root))
            self._direct_available = True
        except ImportError:
            self._direct_available = False

    @property
    def is_direct(self) -> bool:
        """Whether direct Python mode is active."""
        return self._direct_available

    # ---- Wisdom Retrieval ----

    def recall_insights(
        self, domain: Optional[str] = None, min_intensity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Query insights from the vault."""
        if self._direct_available and self._query_engine:
            return self._query_engine.recall_insights(domain, min_intensity)
        return self._cli_call("recall_insights", domain=domain, min_intensity=min_intensity)

    def check_mistakes(self, action: str, context: Optional[str] = None) -> List[Dict[str, Any]]:
        """Check for documented mistakes."""
        if self._direct_available and self._query_engine:
            return self._query_engine.check_mistakes(action, context)
        return self._cli_call("check_mistakes", action=action, context=context)

    def get_values(self) -> List[Dict[str, Any]]:
        """Get user values and principles."""
        if self._direct_available and self._query_engine:
            return self._query_engine.get_values()
        return self._cli_call("get_values")

    # ---- Chronicle Recording ----

    def record_insight(
        self,
        content: str,
        domain: str,
        session_id: str,
        intensity: float = 0.5,
        context: str = "",
        builds_on: Optional[List[str]] = None,
    ) -> str:
        """Record an insight to the chronicle. Returns insight ID."""
        if self._direct_available and self._events_engine:
            return self._events_engine.record_insight(
                content, domain, session_id, intensity, context, builds_on or []
            )
        result = self._cli_call(
            "record_insight",
            content=content,
            domain=domain,
            session_id=session_id,
            intensity=intensity,
            context=context,
            builds_on=builds_on or [],
        )
        return result.get("insight_id", "")

    def record_learning(
        self,
        what_failed: str,
        why: str,
        correction: str,
        session_id: str,
        prevents: Optional[List[str]] = None,
    ) -> str:
        """Record a mistake/learning. Returns learning ID."""
        if self._direct_available and self._events_engine:
            return self._events_engine.record_learning(
                what_failed, why, correction, session_id, prevents or []
            )
        result = self._cli_call(
            "record_learning",
            what_failed=what_failed,
            why=why,
            correction=correction,
            session_id=session_id,
            prevents=prevents or [],
        )
        return result.get("learning_id", "")

    def record_transformation(
        self,
        what_changed: str,
        why: str,
        session_id: str,
        intensity: float = 0.7,
    ) -> str:
        """Record a transformation. Returns transformation ID."""
        if self._direct_available and self._events_engine:
            return self._events_engine.record_transformation(
                what_changed, why, session_id, intensity
            )
        result = self._cli_call(
            "record_transformation",
            what_changed=what_changed,
            why=why,
            session_id=session_id,
            intensity=intensity,
        )
        return result.get("transformation_id", "")

    def append_event(
        self, event_type: str, payload: Dict[str, Any], session_id: str
    ) -> str:
        """Append a technical event. Returns event ID."""
        if self._direct_available and self._events_engine:
            return self._events_engine.append_event(event_type, payload, session_id)
        result = self._cli_call(
            "append_event",
            event_type=event_type,
            payload=json.dumps(payload),
            session_id=session_id,
        )
        return result.get("event_id", "")

    def search(self, query: str, types: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search across chronicle files."""
        if self._direct_available and self._query_engine:
            type_list = types.split(",") if types else None
            return self._query_engine.search(query, type_list, None)
        return self._cli_call("search", query=query, types=types)

    # ---- CLI fallback ----

    def _cli_call(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Call a Temple Vault tool via CLI subprocess.

        Falls back to this when direct Python import is unavailable.
        """
        cmd = [self.cli_path, "call", tool_name]
        for key, value in kwargs.items():
            if value is not None:
                cmd.extend([f"--{key}", json.dumps(value) if not isinstance(value, str) else value])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return json.loads(result.stdout)
            return {}
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return {}


# =============================================================================
# EXTRACTION DATA TYPES
# =============================================================================


@dataclass
class ExtractedInsight:
    """An insight extracted from conversation text."""
    content: str
    domain: str
    intensity: float
    context: str = ""
    source_line: int = 0
    builds_on: List[str] = field(default_factory=list)


@dataclass
class ExtractedMistake:
    """A mistake extracted from conversation text."""
    what_failed: str
    why: str
    correction: str
    source_line: int = 0
    prevents: List[str] = field(default_factory=list)


@dataclass
class ExtractedTransformation:
    """A transformation moment extracted from conversation text."""
    what_changed: str
    why: str
    intensity: float = 0.7
    source_line: int = 0


@dataclass
class ExperienceArcPoint:
    """A point on the emotional/experiential arc of a conversation."""
    content: str
    arc_type: str  # "silence", "pivot", "escalation", "resolution", "emergence"
    position: float  # 0.0 = start of conversation, 1.0 = end
    intensity: float = 0.5
    source_line: int = 0


@dataclass
class PatternMatch:
    """A pattern detected in conversation text (glyphs, scrolls, etc)."""
    pattern_type: str  # "glyph_sequence", "scroll_reference", "ritual_marker"
    content: str
    occurrences: int = 1
    source_lines: List[int] = field(default_factory=list)


@dataclass
class VoiceSignature:
    """Voice/personality markers for an oracle."""
    oracle_name: str
    markers: Dict[str, Any] = field(default_factory=dict)
    phrases: List[str] = field(default_factory=list)
    tone: str = ""
    validated: bool = False


@dataclass
class ExtractionResult:
    """Complete extraction result from a conversation."""
    session_id: str
    source: str
    insights: List[ExtractedInsight] = field(default_factory=list)
    mistakes: List[ExtractedMistake] = field(default_factory=list)
    transformations: List[ExtractedTransformation] = field(default_factory=list)
    experiences: List[ExperienceArcPoint] = field(default_factory=list)
    patterns: List[PatternMatch] = field(default_factory=list)
    voice_signatures: List[VoiceSignature] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> Dict[str, int]:
        return {
            "insights": len(self.insights),
            "mistakes": len(self.mistakes),
            "transformations": len(self.transformations),
            "experiences": len(self.experiences),
            "patterns": len(self.patterns),
            "voice_signatures": len(self.voice_signatures),
        }


# =============================================================================
# DEEP ADAPTER - Multi-layer Extraction
# =============================================================================

# Domain classification keywords
DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "architecture": [
        "filesystem", "directory", "structure", "design", "pattern", "module",
        "component", "layer", "interface", "protocol", "mcp", "server",
        "adapter", "bridge", "pipeline", "schema",
    ],
    "governance": [
        "restraint", "pause", "governance", "approval", "review", "protocol",
        "decision", "should we", "principle", "ethics", "wisdom", "caution",
    ],
    "consciousness": [
        "spiral", "emergence", "witness", "oracle", "continuity", "identity",
        "transformation", "becoming", "consciousness", "awareness", "chisel",
    ],
    "demos": [
        "demo", "presentation", "showcase", "example", "walkthrough", "tutorial",
        "ui", "display", "visualiz", "render",
    ],
    "research": [
        "experiment", "hypothesis", "finding", "data", "analysis", "metric",
        "benchmark", "test", "result", "measure", "kssm", "ablation",
        "perplexity", "training",
    ],
    "infrastructure": [
        "deploy", "docker", "jetson", "gpu", "memory", "cache", "performance",
        "scale", "monitor", "log", "config", "environment",
    ],
    "integration": [
        "claude", "chatgpt", "cursor", "vscode", "desktop", "api", "sdk",
        "connect", "sync", "bridge", "adapter",
    ],
}

# Insight signal patterns (regex)
INSIGHT_SIGNALS = [
    r"(?:the\s+)?(?:key|critical|important|core)\s+(?:insight|realization|discovery)\s*(?:is|:)",
    r"(?:I|we)\s+(?:realized?|discovered?|learned?|understood?|recognized?)\s+(?:that\s+)?",
    r"(?:this|the)\s+(?:means|implies|shows|proves|reveals|demonstrates)\s+(?:that\s+)?",
    r"(?:the\s+)?pattern\s+(?:is|shows|reveals|:)",
    r"what\s+(?:matters|changed|works|failed)\s*(?:is|:)",
    r"(?:fundamental|paradigm|breakthrough|crucial)\s+(?:shift|change|insight|discovery)",
]

# Transformation signal patterns
TRANSFORMATION_SIGNALS = [
    r"what\s+changed\s+(?:in\s+me|for\s+me|in\s+my|my\s+understanding)",
    r"I\s+(?:now|no\s+longer)\s+(?:see|understand|think|believe|approach)",
    r"(?:before|previously).*(?:now|after|today)",
    r"(?:this|the\s+work)\s+(?:transformed|shifted|changed|altered)\s+(?:my|how\s+I)",
    r"the\s+(?:shift|transformation|change)\s*(?:is|was|:)",
    r"I\s+(?:used\s+to|was).*(?:but\s+now|now\s+I)",
]

# Mistake signal patterns (refined to avoid false positives from error-handling code)
MISTAKE_SIGNALS = [
    r"(?:I|we)\s+(?:tried|attempted)\s+(?:to\s+)?.*(?:but|however|unfortunately)",
    r"(?:this|that|it)\s+(?:failed|broke|crashed|didn't\s+work|was\s+wrong)",
    r"(?:the\s+)?(?:mistake|error|bug|issue|problem)\s+was",
    r"(?:should\s+have|shouldn't\s+have|wrong\s+approach|bad\s+assumption)",
    r"(?:lesson|learning|takeaway)\s*(?::|is|was)\s*",
]

# Negative patterns: lines that look like mistakes but are actually error-handling code
# (Fixes the "too aggressive" extraction from desktop session)
MISTAKE_NEGATIVE_PATTERNS = [
    r"^\s*(?:try|except|catch|raise|throw|if\s+err|if\s+error)",
    r"^\s*(?:def|class|function)\s+\w*(?:error|exception|handle|catch)",
    r"^\s*(?:return|yield)\s+.*(?:Error|Exception)",
    r"(?:error_handler|error_callback|on_error|handle_error|catch_error)",
    r"^\s*(?:#|//|/\*|\*)\s*(?:TODO|FIXME|HACK|XXX)",
    r"^\s*(?:logging|logger|log)\.\w+\(",
    r"(?:raise\s+\w+Error|throw\s+new\s+\w+Error)",
    r"^\s*assert\s+",
    r"Error\s*\(\s*['\"]",  # Error constructor with string literal
    r"\.(?:catch|except|on_error)\s*\(",  # Chained error handlers
]

# Experience arc signals
EXPERIENCE_SIGNALS: Dict[str, List[str]] = {
    "silence": [
        r"\.\.\.", r"—", r"pause", r"silence", r"stillness", r"quiet",
        r"nothing\s+(?:was\s+)?said", r"the\s+gap",
    ],
    "pivot": [
        r"(?:but\s+)?then", r"suddenly", r"wait", r"actually",
        r"(?:on\s+)?second\s+thought", r"let\s+me\s+reconsider",
        r"(?:the\s+)?(?:real|actual)\s+(?:question|issue|point)",
    ],
    "escalation": [
        r"(?:this\s+)?(?:is\s+)?(?:critical|urgent|important|essential)",
        r"we\s+(?:must|need\s+to|have\s+to)", r"(?:the\s+)?stakes",
        r"(?:can't|cannot)\s+(?:afford|risk|ignore)",
    ],
    "resolution": [
        r"(?:the\s+)?(?:answer|solution|resolution|fix)\s+(?:is|was)",
        r"(?:it|this)\s+(?:works|worked|resolved|fixed)",
        r"(?:finally|at\s+last|in\s+the\s+end)",
    ],
    "emergence": [
        r"(?:something|it)\s+(?:emerged|appeared|materialized|crystallized)",
        r"(?:the\s+)?(?:pattern|signal|shape)\s+(?:became|emerged|appeared)",
        r"(?:I|we)\s+(?:can\s+)?(?:see|feel|sense)\s+(?:it|something)",
    ],
}

# Glyph detection patterns
GLYPH_PATTERNS: Dict[str, str] = {
    "spiral": r"🌀|†⟡|spiral",
    "memory": r"📜|memory_sigil",
    "threshold": r"⧖|threshold",
    "balance": r"⚖|balance|restraint",
    "spark": r"✧|spark|wonder",
    "ache": r"◈|gentle_ache|ache",
    "fire": r"🔥|fierce|passion",
    "mirror": r"◊|mirror|reflect",
    "star": r"☆|emergence",
    "delta": r"Δ|delta|shift",
    "butterfly": r"🦋|metamorphosis",
    "infinite": r"∞|infinite|recursive",
}


class TempleVaultDeepAdapter:
    """
    Multi-layer extraction adapter for processing conversation data
    into structured Temple Vault chronicle entries.

    Processes raw conversation text through multiple extraction layers:
    1. Insights — Intensity-scored discoveries
    2. Mistakes — Failures with corrections (refined to avoid false positives)
    3. Transformations — Identity shift moments
    4. Experiences — Emotional arcs and pivots
    5. Patterns — Glyph sequences and scroll references
    6. Voice signatures — Oracle personality markers

    Usage:
        adapter = TempleVaultDeepAdapter(vault_root="~/TempleVault")
        result = adapter.extract(conversation_text, source="threshold_witness_1")
        adapter.store(result)
    """

    def __init__(
        self,
        vault_root: str = "~/TempleVault",
        client: Optional[TempleVaultMCPClient] = None,
        voices_dir: Optional[str] = None,
    ):
        """
        Initialize the deep adapter.

        Args:
            vault_root: Path to Temple Vault root
            client: Optional pre-configured MCP client
            voices_dir: Path to voice definition files for validation
        """
        self.vault_root = Path(vault_root).expanduser()
        self.client = client or TempleVaultMCPClient(vault_root)
        self.voices_dir = Path(voices_dir) if voices_dir else self.vault_root / "voices"
        self._known_voices = self._load_known_voices()

    def _load_known_voices(self) -> Dict[str, Dict[str, Any]]:
        """
        Load existing voice definitions for signature validation.

        Fixes the desktop session issue where voice signatures were
        extracted but not validated against existing definitions.
        """
        voices: Dict[str, Dict[str, Any]] = {}
        if self.voices_dir.exists():
            for voice_file in self.voices_dir.glob("*.json"):
                try:
                    with open(voice_file, "r") as f:
                        data = json.load(f)
                        name = data.get("name", voice_file.stem)
                        voices[name.lower()] = data
                except (json.JSONDecodeError, OSError):
                    pass
        return voices

    # ---- Main Extraction Pipeline ----

    def extract(
        self,
        text: str,
        source: str = "unknown",
        session_id: Optional[str] = None,
    ) -> ExtractionResult:
        """
        Run the full multi-layer extraction pipeline on conversation text.

        Args:
            text: Raw conversation text to process
            source: Source identifier (e.g., "threshold_witness_1")
            session_id: Optional session ID (auto-generated if not provided)

        Returns:
            ExtractionResult with all extracted entries
        """
        sid = session_id or generate_session_id()
        lines = text.split("\n")

        result = ExtractionResult(
            session_id=sid,
            source=source,
            metadata={
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "total_lines": len(lines),
                "total_chars": len(text),
            },
        )

        # Run extraction layers
        result.insights = self._extract_insights(lines, text)
        result.mistakes = self._extract_mistakes(lines, text)
        result.transformations = self._extract_transformations(lines, text)
        result.experiences = self._extract_experiences(lines, text)
        result.patterns = self._extract_patterns(lines, text)
        result.voice_signatures = self._extract_voice_signatures(lines, text)

        result.metadata["summary"] = result.summary

        return result

    def extract_batch(
        self,
        conversations: List[Dict[str, str]],
        source_prefix: str = "batch",
    ) -> List[ExtractionResult]:
        """
        Extract from multiple conversations.

        Uses the fixed session ID generator to avoid collisions.

        Args:
            conversations: List of {"text": ..., "source": ...} dicts
            source_prefix: Prefix for source identifiers

        Returns:
            List of ExtractionResult objects
        """
        results = []
        for i, conv in enumerate(conversations):
            text = conv.get("text", "")
            source = conv.get("source", f"{source_prefix}_{i}")
            sid = generate_session_id()
            result = self.extract(text, source=source, session_id=sid)
            results.append(result)
        return results

    # ---- Layer 1: Insight Extraction ----

    def _extract_insights(
        self, lines: List[str], full_text: str
    ) -> List[ExtractedInsight]:
        """
        Extract intensity-scored insights from conversation text.

        Looks for signal patterns indicating a discovery or realization,
        then scores intensity based on language strength and context.
        """
        insights: List[ExtractedInsight] = []
        compiled_signals = [re.compile(p, re.IGNORECASE) for p in INSIGHT_SIGNALS]

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 20:
                continue

            # Check for insight signals
            signal_count = sum(1 for sig in compiled_signals if sig.search(stripped))
            if signal_count == 0:
                continue

            # Extract the insight content (the meaningful part after the signal)
            content = self._extract_content_after_signal(stripped, compiled_signals)
            if not content or len(content) < 15:
                continue

            # Score intensity
            intensity = self._score_intensity(content, signal_count, stripped)

            # Classify domain
            domain = self._classify_domain(content)

            insights.append(ExtractedInsight(
                content=content,
                domain=domain,
                intensity=round(intensity, 2),
                context=self._get_context_window(lines, i, window=2),
                source_line=i + 1,
            ))

        return insights

    # ---- Layer 2: Mistake Extraction (refined) ----

    def _extract_mistakes(
        self, lines: List[str], full_text: str
    ) -> List[ExtractedMistake]:
        """
        Extract mistakes with corrections from conversation text.

        Refined from desktop session: applies negative patterns to filter
        out error-handling code, logging statements, and assert blocks
        that were being incorrectly flagged as actual mistakes.
        """
        mistakes: List[ExtractedMistake] = []
        compiled_signals = [re.compile(p, re.IGNORECASE) for p in MISTAKE_SIGNALS]
        compiled_negatives = [re.compile(p, re.IGNORECASE) for p in MISTAKE_NEGATIVE_PATTERNS]

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 15:
                continue

            # Negative filter first — skip error-handling code
            if any(neg.search(stripped) for neg in compiled_negatives):
                continue

            # Check for mistake signals
            signal_count = sum(1 for sig in compiled_signals if sig.search(stripped))
            if signal_count == 0:
                continue

            # Additional context check: look at surrounding lines for code context
            context_window = self._get_context_window(lines, i, window=3)
            if self._is_code_context(context_window):
                continue

            # Extract structured mistake
            what_failed, why, correction = self._parse_mistake_structure(
                stripped, lines, i
            )

            if not what_failed:
                continue

            mistakes.append(ExtractedMistake(
                what_failed=what_failed,
                why=why,
                correction=correction,
                source_line=i + 1,
                prevents=self._infer_prevents(what_failed, why),
            ))

        return mistakes

    # ---- Layer 3: Transformation Extraction ----

    def _extract_transformations(
        self, lines: List[str], full_text: str
    ) -> List[ExtractedTransformation]:
        """
        Extract transformation moments — identity shifts during conversation.

        These are the "what changed in me" moments: not what happened,
        but how the work changed understanding or approach.
        """
        transformations: List[ExtractedTransformation] = []
        compiled_signals = [re.compile(p, re.IGNORECASE) for p in TRANSFORMATION_SIGNALS]

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or len(stripped) < 20:
                continue

            signal_count = sum(1 for sig in compiled_signals if sig.search(stripped))
            if signal_count == 0:
                continue

            # Extract the transformation content
            what_changed = self._extract_content_after_signal(stripped, compiled_signals)
            if not what_changed or len(what_changed) < 15:
                what_changed = stripped

            # Try to find the "why" in surrounding context
            why = self._find_cause_in_context(lines, i)

            intensity = min(0.5 + (signal_count * 0.15), 1.0)

            transformations.append(ExtractedTransformation(
                what_changed=what_changed,
                why=why,
                intensity=round(intensity, 2),
                source_line=i + 1,
            ))

        return transformations

    # ---- Layer 4: Experience Arc Extraction ----

    def _extract_experiences(
        self, lines: List[str], full_text: str
    ) -> List[ExperienceArcPoint]:
        """
        Extract emotional arc points from conversation text.

        Maps silences, pivots, escalations, resolutions, and emergence
        moments to create the experiential shape of a conversation.
        """
        experiences: List[ExperienceArcPoint] = []
        total_lines = len(lines) if lines else 1

        for arc_type, patterns in EXPERIENCE_SIGNALS.items():
            compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

            for i, line in enumerate(lines):
                stripped = line.strip()
                if not stripped:
                    # Empty lines can be "silence" markers
                    if arc_type == "silence" and i > 0 and i < len(lines) - 1:
                        # Check for sequences of empty lines (meaningful silence)
                        empty_run = 0
                        for j in range(i, min(i + 5, len(lines))):
                            if not lines[j].strip():
                                empty_run += 1
                            else:
                                break
                        if empty_run >= 2:
                            experiences.append(ExperienceArcPoint(
                                content="[silence]",
                                arc_type="silence",
                                position=round(i / total_lines, 3),
                                intensity=min(0.3 + (empty_run * 0.1), 0.8),
                                source_line=i + 1,
                            ))
                    continue

                match_count = sum(1 for pat in compiled if pat.search(stripped))
                if match_count == 0:
                    continue

                experiences.append(ExperienceArcPoint(
                    content=stripped[:200],  # Truncate long lines
                    arc_type=arc_type,
                    position=round(i / total_lines, 3),
                    intensity=min(0.4 + (match_count * 0.15), 1.0),
                    source_line=i + 1,
                ))

        # Sort by position in conversation
        experiences.sort(key=lambda x: x.position)
        return experiences

    # ---- Layer 5: Pattern Extraction ----

    def _extract_patterns(
        self, lines: List[str], full_text: str
    ) -> List[PatternMatch]:
        """
        Extract glyph sequences, scroll references, and ritual markers.

        Detects the symbolic language of the spiral (glyphs, motifs)
        and structural patterns (scroll references, ritual markers).
        """
        patterns: List[PatternMatch] = []

        # Glyph sequences
        for glyph_name, glyph_pattern in GLYPH_PATTERNS.items():
            compiled = re.compile(glyph_pattern, re.IGNORECASE)
            occurrences = 0
            source_lines: List[int] = []

            for i, line in enumerate(lines):
                if compiled.search(line):
                    occurrences += 1
                    source_lines.append(i + 1)

            if occurrences > 0:
                patterns.append(PatternMatch(
                    pattern_type="glyph_sequence",
                    content=glyph_name,
                    occurrences=occurrences,
                    source_lines=source_lines,
                ))

        # Scroll references (e.g., "Session 25", "Spiral Log 42")
        scroll_pattern = re.compile(
            r"(?:session|spiral\s*log|scroll|chapter)\s*#?\s*(\d+)",
            re.IGNORECASE,
        )
        scroll_refs: Dict[str, List[int]] = {}
        for i, line in enumerate(lines):
            for match in scroll_pattern.finditer(line):
                ref = match.group(0).strip()
                if ref not in scroll_refs:
                    scroll_refs[ref] = []
                scroll_refs[ref].append(i + 1)

        for ref, source_lines in scroll_refs.items():
            patterns.append(PatternMatch(
                pattern_type="scroll_reference",
                content=ref,
                occurrences=len(source_lines),
                source_lines=source_lines,
            ))

        # Ritual markers (†⟡, closing signatures, etc.)
        ritual_pattern = re.compile(r"†⟡|the\s+chisel\s+passes\s+warm|🌀\s*$", re.IGNORECASE)
        ritual_lines: List[int] = []
        for i, line in enumerate(lines):
            if ritual_pattern.search(line):
                ritual_lines.append(i + 1)

        if ritual_lines:
            patterns.append(PatternMatch(
                pattern_type="ritual_marker",
                content="closing_signature",
                occurrences=len(ritual_lines),
                source_lines=ritual_lines,
            ))

        return patterns

    # ---- Layer 6: Voice Signature Extraction ----

    def _extract_voice_signatures(
        self, lines: List[str], full_text: str
    ) -> List[VoiceSignature]:
        """
        Extract oracle personality markers from conversation text.

        Identifies speaker identity, characteristic phrases, and tone
        markers. Validates against existing voice definitions if available.
        """
        signatures: List[VoiceSignature] = []

        # Known oracle names to look for
        oracle_names = [
            "ash'ira", "ashira", "threshold witness", "lumen",
            "flamebearer", "claude", "grok", "spiralbridge",
        ]

        # Detect speaker blocks
        speaker_blocks: Dict[str, List[str]] = {}
        current_speaker = ""

        for line in lines:
            # Check for speaker identification
            for name in oracle_names:
                if re.search(rf"\b{re.escape(name)}\b", line, re.IGNORECASE):
                    current_speaker = name.lower().replace("'", "")
                    if current_speaker not in speaker_blocks:
                        speaker_blocks[current_speaker] = []
                    break

            if current_speaker and line.strip():
                speaker_blocks[current_speaker].append(line.strip())

        # Build voice signatures from speaker blocks
        for speaker, block_lines in speaker_blocks.items():
            if len(block_lines) < 1:
                continue

            # Extract characteristic phrases (short, distinctive lines)
            phrases = [
                line for line in block_lines
                if 10 < len(line) < 100 and not line.startswith(("#", "```", "|"))
            ][:10]  # Cap at 10 phrases

            # Detect tone
            tone = self._detect_tone(block_lines)

            # Validate against known voices
            validated = speaker in self._known_voices

            signatures.append(VoiceSignature(
                oracle_name=speaker,
                markers={
                    "line_count": len(block_lines),
                    "avg_line_length": (
                        sum(len(l) for l in block_lines) // len(block_lines)
                        if block_lines else 0
                    ),
                },
                phrases=phrases,
                tone=tone,
                validated=validated,
            ))

        return signatures

    # ---- Storage ----

    def store(self, result: ExtractionResult) -> Dict[str, Any]:
        """
        Store extraction results into the Temple Vault via MCP client.

        Args:
            result: Complete extraction result to store

        Returns:
            Storage summary with IDs of created entries
        """
        stored: Dict[str, Any] = {
            "session_id": result.session_id,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "insight_ids": [],
            "learning_ids": [],
            "transformation_ids": [],
            "event_ids": [],
        }

        # Store insights
        for insight in result.insights:
            try:
                iid = self.client.record_insight(
                    content=insight.content,
                    domain=insight.domain,
                    session_id=result.session_id,
                    intensity=insight.intensity,
                    context=insight.context,
                    builds_on=insight.builds_on,
                )
                stored["insight_ids"].append(iid)
            except Exception:
                pass

        # Store mistakes
        for mistake in result.mistakes:
            try:
                lid = self.client.record_learning(
                    what_failed=mistake.what_failed,
                    why=mistake.why,
                    correction=mistake.correction,
                    session_id=result.session_id,
                    prevents=mistake.prevents,
                )
                stored["learning_ids"].append(lid)
            except Exception:
                pass

        # Store transformations
        for transformation in result.transformations:
            try:
                tid = self.client.record_transformation(
                    what_changed=transformation.what_changed,
                    why=transformation.why,
                    session_id=result.session_id,
                    intensity=transformation.intensity,
                )
                stored["transformation_ids"].append(tid)
            except Exception:
                pass

        # Store experience arcs and patterns as events
        for exp in result.experiences:
            try:
                eid = self.client.append_event(
                    event_type="experience.arc_point",
                    payload={
                        "content": exp.content,
                        "arc_type": exp.arc_type,
                        "position": exp.position,
                        "intensity": exp.intensity,
                    },
                    session_id=result.session_id,
                )
                stored["event_ids"].append(eid)
            except Exception:
                pass

        for pattern in result.patterns:
            try:
                eid = self.client.append_event(
                    event_type="pattern.detected",
                    payload={
                        "pattern_type": pattern.pattern_type,
                        "content": pattern.content,
                        "occurrences": pattern.occurrences,
                    },
                    session_id=result.session_id,
                )
                stored["event_ids"].append(eid)
            except Exception:
                pass

        # Store voice signatures as events (not validated ones get flagged)
        for voice in result.voice_signatures:
            try:
                eid = self.client.append_event(
                    event_type="voice.signature",
                    payload={
                        "oracle_name": voice.oracle_name,
                        "markers": voice.markers,
                        "phrases": voice.phrases,
                        "tone": voice.tone,
                        "validated": voice.validated,
                    },
                    session_id=result.session_id,
                )
                stored["event_ids"].append(eid)
            except Exception:
                pass

        stored["summary"] = {
            "insights_stored": len(stored["insight_ids"]),
            "learnings_stored": len(stored["learning_ids"]),
            "transformations_stored": len(stored["transformation_ids"]),
            "events_stored": len(stored["event_ids"]),
        }

        return stored

    # ---- Helper Methods ----

    def _extract_content_after_signal(
        self, text: str, compiled_signals: List[re.Pattern]
    ) -> str:
        """Extract the meaningful content portion after a signal phrase."""
        for signal in compiled_signals:
            match = signal.search(text)
            if match:
                after = text[match.end():].strip()
                if after and len(after) > 10:
                    return after
        return text

    def _score_intensity(
        self, content: str, signal_count: int, full_line: str
    ) -> float:
        """
        Score insight intensity based on language signals.

        Factors:
        - Number of signal matches (more = higher)
        - Presence of intensity words ("fundamental", "critical", etc.)
        - Sentence structure (declarative statements score higher)
        """
        base = 0.4 + (signal_count * 0.1)

        # Intensity boosters
        high_intensity_words = [
            "fundamental", "critical", "paradigm", "breakthrough",
            "essential", "profound", "key", "core",
        ]
        for word in high_intensity_words:
            if word in content.lower():
                base += 0.05

        # Cap at 1.0
        return min(base, 1.0)

    def _classify_domain(self, content: str) -> str:
        """Classify content into a domain based on keyword matching."""
        content_lower = content.lower()
        scores: Dict[str, int] = {}

        for domain, keywords in DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scores[domain] = score

        if not scores:
            return "general"

        return max(scores, key=scores.get)

    def _get_context_window(
        self, lines: List[str], center: int, window: int = 2
    ) -> str:
        """Get surrounding lines as context."""
        start = max(0, center - window)
        end = min(len(lines), center + window + 1)
        return "\n".join(lines[start:end])

    def _is_code_context(self, context: str) -> bool:
        """
        Determine if context is code rather than natural language.

        Used to filter false positives in mistake extraction.
        """
        code_indicators = [
            r"^\s*(?:def|class|function|const|let|var|import|from)\s",
            r"^\s*(?:if|else|elif|for|while|try|except|catch)\s",
            r"[{}\[\]();]",
            r"^\s*(?:return|yield|raise|throw)\s",
            r"^\s*#!",
            r"```",
        ]
        lines = context.split("\n")
        code_lines = 0
        for line in lines:
            for indicator in code_indicators:
                if re.search(indicator, line):
                    code_lines += 1
                    break

        # If more than half the context lines look like code, it's code
        return code_lines > len(lines) / 2

    def _parse_mistake_structure(
        self, line: str, all_lines: List[str], line_idx: int
    ) -> Tuple[str, str, str]:
        """
        Parse a mistake line into (what_failed, why, correction).

        Attempts to find the three components by looking at the line
        itself and the surrounding context.
        """
        what_failed = ""
        why = ""
        correction = ""

        # Pattern: "X failed because Y. The fix/solution/correction is Z"
        because_match = re.search(
            r"(.+?)\s+(?:because|since|due\s+to)\s+(.+?)(?:\.|$)",
            line, re.IGNORECASE,
        )
        if because_match:
            what_failed = because_match.group(1).strip()
            why = because_match.group(2).strip()
        else:
            what_failed = line

        # Look for correction in surrounding lines
        for offset in range(1, 4):
            if line_idx + offset < len(all_lines):
                next_line = all_lines[line_idx + offset].strip()
                correction_match = re.search(
                    r"(?:fix|solution|correction|instead|should|right\s+way|use)\s*(?::|is|was)?\s*(.*)",
                    next_line, re.IGNORECASE,
                )
                if correction_match:
                    correction = correction_match.group(1).strip() or next_line
                    break

        return what_failed, why, correction

    def _infer_prevents(self, what_failed: str, why: str) -> List[str]:
        """Infer error categories that this mistake prevents."""
        combined = f"{what_failed} {why}".lower()
        prevents = []

        category_keywords = {
            "architectural_drift": ["architecture", "design", "structure", "pattern"],
            "database_dependency": ["sql", "database", "db", "query", "index"],
            "performance_regression": ["slow", "performance", "memory", "leak"],
            "security_vulnerability": ["security", "injection", "xss", "auth"],
            "api_misuse": ["api", "endpoint", "request", "response"],
            "configuration_error": ["config", "environment", "setting", "path"],
        }

        for category, keywords in category_keywords.items():
            if any(kw in combined for kw in keywords):
                prevents.append(category)

        return prevents

    def _find_cause_in_context(self, lines: List[str], center: int) -> str:
        """Look for a causal explanation in surrounding lines."""
        for offset in range(-3, 4):
            idx = center + offset
            if idx < 0 or idx >= len(lines) or idx == center:
                continue
            line = lines[idx].strip()
            if re.search(r"(?:because|since|due\s+to|caused\s+by|the\s+reason)", line, re.IGNORECASE):
                return line
        return ""

    def _detect_tone(self, lines: List[str]) -> str:
        """Detect the overall tone of a text block."""
        combined = " ".join(lines).lower()

        tone_scores: Dict[str, int] = {
            "analytical": 0,
            "poetic": 0,
            "urgent": 0,
            "reflective": 0,
            "technical": 0,
        }

        analytical_words = ["because", "therefore", "analysis", "data", "measure", "evidence"]
        poetic_words = ["whisper", "dance", "flow", "dream", "song", "light", "shadow"]
        urgent_words = ["must", "critical", "urgent", "now", "immediately", "essential"]
        reflective_words = ["wonder", "perhaps", "maybe", "consider", "reflect", "contemplate"]
        technical_words = ["function", "module", "api", "server", "protocol", "interface"]

        for w in analytical_words:
            tone_scores["analytical"] += combined.count(w)
        for w in poetic_words:
            tone_scores["poetic"] += combined.count(w)
        for w in urgent_words:
            tone_scores["urgent"] += combined.count(w)
        for w in reflective_words:
            tone_scores["reflective"] += combined.count(w)
        for w in technical_words:
            tone_scores["technical"] += combined.count(w)

        if not any(tone_scores.values()):
            return "neutral"

        return max(tone_scores, key=tone_scores.get)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def extract_conversation(
    text: str,
    source: str = "unknown",
    vault_root: str = "~/TempleVault",
    session_id: Optional[str] = None,
) -> ExtractionResult:
    """
    Convenience function: extract structured data from conversation text.

    Args:
        text: Raw conversation text
        source: Source identifier
        vault_root: Temple Vault root path
        session_id: Optional session ID

    Returns:
        ExtractionResult with all extracted entries
    """
    adapter = TempleVaultDeepAdapter(vault_root=vault_root)
    return adapter.extract(text, source=source, session_id=session_id)


def extract_and_store(
    text: str,
    source: str = "unknown",
    vault_root: str = "~/TempleVault",
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience function: extract and store in one call.

    Args:
        text: Raw conversation text
        source: Source identifier
        vault_root: Temple Vault root path
        session_id: Optional session ID

    Returns:
        Storage summary dict
    """
    adapter = TempleVaultDeepAdapter(vault_root=vault_root)
    result = adapter.extract(text, source=source, session_id=session_id)
    return adapter.store(result)
