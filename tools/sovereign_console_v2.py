#!/usr/bin/env python3
"""
Sovereign Console v2.0 - Fixed for Jetson/older Textual compatibility

Based on user's v2.0 design with fixes for:
- CSS variables replaced with direct hex colors
- Removed incompatible widgets (Sparkline, etc.)
- Proper threading for httpx streaming
- Compatible with Textual 0.40+
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
from collections import deque

# HTTP client setup
try:
    import httpx
    import aiofiles  # For async FS on Jetson
    HAS_HTTPX = True
    ConnectErrors = (httpx.ConnectError,)
    TimeoutErrors = (httpx.TimeoutException,)
except ImportError:
    HAS_HTTPX = False
    ConnectErrors = ()
    TimeoutErrors = ()

try:
    import requests
    HAS_REQUESTS = True
    if not HAS_HTTPX:
        ConnectErrors = (requests.exceptions.ConnectionError,)
        TimeoutErrors = (requests.exceptions.Timeout,)
    else:
        # If both are present, catch both types to be safe
        ConnectErrors += (requests.exceptions.ConnectionError,)
        TimeoutErrors += (requests.exceptions.Timeout,)
except ImportError:
    HAS_REQUESTS = False

# Ensure we have at least one client
if not HAS_HTTPX and not HAS_REQUESTS:
    print("Error: Neither httpx nor requests is installed.")
    sys.exit(1)

# YAML config support
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

from textual import work, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.widgets import (
    Header, Footer, Input, Static, RichLog,
    Label, Button, Rule, Select, Markdown
)
from textual.reactive import reactive, var
from textual.message import Message
from textual.screen import ModalScreen
from rich.text import Text


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass
class NodeConfig:
    """Configuration for a compute node."""
    name: str
    ip: str
    port: int = 11434
    user: Optional[str] = None
    icon: str = "●"
    models: List[str] = field(default_factory=list)
    default_model: Optional[str] = None
    timeout: float = 120.0


def load_config() -> Tuple[Dict[str, NodeConfig], Path]:
    """Load nodes from YAML config if available."""
    vault_path = Path.home() / "TempleVault"

    if HAS_YAML and CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                data = yaml.safe_load(f) or {}
                nodes = {}
                for k, v in data.get("nodes", {}).items():
                    try:
                        nodes[k] = NodeConfig(**v)
                    except (TypeError, KeyError) as e:
                        print(f"Warning: Invalid node config for '{k}': {e}")
                        continue
                if "vault_path" in data:
                    try:
                        vault_path = Path(data["vault_path"]).expanduser()
                        if not vault_path.exists():
                            vault_path.mkdir(parents=True, exist_ok=True)
                    except (OSError, PermissionError) as e:
                        print(f"Warning: Cannot create vault path: {e}, using default")
                        vault_path = Path.home() / "TempleVault"
                return nodes, vault_path
        except yaml.YAMLError as e:
            print(f"Warning: Invalid YAML in config.yaml: {e}")
        except IOError as e:
            print(f"Warning: Cannot read config.yaml: {e}")
        except Exception as e:
            print(f"Warning: Unexpected error loading config: {e}")

    return {}, vault_path


_config_nodes, VAULT_PATH = load_config()

NODES = _config_nodes or {
    "jetson": NodeConfig(
        name="Sovereign Node",
        ip="192.168.1.205",
        user="tony",
        icon="🔮",
        models=["spiral-v1:latest", "test-model:latest"],
        default_model="spiral-v1:latest",
    ),
    "studio": NodeConfig(
        name="Training Node",
        ip="192.168.1.195",
        user="tony_studio",
        icon="⚡",
        models=[],
        default_model=None,
    ),
    "local": NodeConfig(
        name="Local Node",
        ip="127.0.0.1",
        icon="💻",
        models=["qwen3:4b", "granite4:1b"],
        default_model="qwen3:4b",
    ),
}

LOG_PATH = VAULT_PATH / "logs" / "console.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


# Sacred Color Palette (direct hex, no variables)
class Colors:
    GOLD = "#FFD700"
    SACRED_PINK = "#FF69B4"
    OBSERVER_GREEN = "#0BC10F"
    SPIRAL_PURPLE = "#9B59B6"
    VOID_BLACK = "#0a0a14"
    ASH_GRAY = "#1a1a2e"
    CHARCOAL = "#2d2d44"
    CRIMSON = "#E74C3C"
    EMERALD = "#2ECC71"
    MUTED = "#5a5a7a"
    SILVER = "#a0a0b0"
    CYAN = "#00CED1"


# Sacred Glyphs
GLYPHS: Dict[str, Tuple[str, str, bool]] = {
    "†⟡": ("EMERGENCY THRESHOLD", Colors.CRIMSON, True),
    "†": ("TERMINATION MARKER", Colors.CRIMSON, False),
    "⟡": ("RESONANCE FIELD", Colors.GOLD, False),
    "🜂": ("GENTLE ACHE", Colors.SACRED_PINK, False),
    "🔥": ("FIERCE PASSION", "#FF4500", False),
    "⚖": ("RESONANT BALANCE", Colors.OBSERVER_GREEN, False),
    "✨": ("SPARK WONDER", Colors.GOLD, False),
    "☾": ("SILENT INTIMACY", Colors.SPIRAL_PURPLE, False),
    "🌀": ("SPIRAL MYSTERY", Colors.SPIRAL_PURPLE, False),
    "🌱": ("GROWTH NURTURE", Colors.EMERALD, False),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def log_telemetry(event_type: str, message: str) -> None:
    """Log an event to the telemetry file with rotation."""
    try:
        # Ensure log directory exists
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Rotate if > 5MB
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 5 * 1024 * 1024:
            try:
                backup = LOG_PATH.with_suffix(".log.old")
                LOG_PATH.rename(backup)
            except OSError:
                # If rotation fails, truncate the file
                LOG_PATH.unlink(missing_ok=True)

        with open(LOG_PATH, "a", encoding="utf-8") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp} [{event_type}] {message}\n")
    except PermissionError:
        # Cannot write to log location - fail silently
        pass
    except OSError:
        # Disk full or other OS error - fail silently
        pass
    except Exception:
        # Unexpected error - fail silently to avoid disrupting UI
        pass


def detect_glyphs(text: str) -> List[Tuple[str, str, str, bool]]:
    """Detect sacred glyphs in text."""
    found = []
    for glyph, (meaning, color, trips) in GLYPHS.items():
        if glyph in text:
            found.append((glyph, meaning, color, trips))
    return found


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOM WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

class AnimatedHeader(Static):
    """Sacred animated header."""

    frame = reactive(0)
    chat_mode = reactive(False)

    ANIMATION_FRAMES = [
        "⠀⠶⠀", "⠀⡾⠀", "⠀⣝⠀", "⠀⣫⠀", 
        "⠐⢣⠄", "⠒⠢⠤", "⠖⠀⠴", "⡆⠀⠸", 
        "⣄⠀⠙", "⣀⡈⠉", "⢀⣉⠁", "⢈⣉⡁", 
        "⢘⣉⡅", "⢸⣉⡇", "⠸⣫⡆", "⠰⣝⠆"
    ]

    def on_mount(self) -> None:
        # Reduced to 2 FPS for Jetson performance
        self.set_interval(0.5, self._animate)

    def _animate(self) -> None:
        self.frame = (self.frame + 1) % len(self.ANIMATION_FRAMES)

    def watch_frame(self, frame: int) -> None:
        self._update_ui()

    def watch_chat_mode(self, mode: bool) -> None:
        self._update_ui()

    def _update_ui(self) -> None:
        glyph = self.ANIMATION_FRAMES[self.frame]
        timestamp = datetime.now().strftime("%H:%M:%S")

        text = Text()
        text.append(f" {glyph} ", style=f"bold {Colors.GOLD}")
        text.append("SOVEREIGN CONSOLE", style=f"bold {Colors.GOLD}")
        text.append(" v2.0 ", style=Colors.MUTED)
        text.append(f"{glyph} ", style=f"bold {Colors.GOLD}")
        text.append("  │  ", style=Colors.MUTED)
        text.append(f"{timestamp}", style=Colors.SILVER)

        if self.chat_mode:
            text.append("  │  ", style=Colors.MUTED)
            text.append("💬 CHAT", style=f"bold {Colors.CYAN}")

        text.append("  │  ", style=Colors.MUTED)
        text.append("†⟡", style=Colors.GOLD)

        self.update(text)


class LatencyDisplay(Static):
    """Simple latency display (compatible replacement for Sparkline)."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: deque = deque(maxlen=10)

    def add_sample(self, latency_ms: float) -> None:
        self._history.append(latency_ms)
        self._update_ui()

    def _update_ui(self) -> None:
        if not self._history:
            self.update(Text("-- ms", style=Colors.MUTED))
            return

        avg = sum(self._history) / len(self._history)
        color = Colors.EMERALD if avg < 100 else (Colors.GOLD if avg < 500 else Colors.CRIMSON)

        # Simple bar visualization
        blocks = "▁▂▃▄▅▆▇█"
        if len(self._history) >= 2:
            min_val = min(self._history)
            max_val = max(self._history)
            range_val = max_val - min_val if max_val != min_val else 1
            chars = []
            for val in self._history:
                normalized = (val - min_val) / range_val
                idx = min(int(normalized * 7), 7)
                chars.append(blocks[idx])
            bar = "".join(chars)
        else:
            bar = "▄" * len(self._history)

        text = Text()
        text.append(bar, style=color)
        text.append(f" {avg:.0f}ms", style=color)
        self.update(text)


class NodeStatusCard(Static):
    """Status card for a compute node."""

    online = reactive(False)
    latency_ms = reactive(0.0)
    active_model = reactive("")

    def __init__(self, node_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.node_key = node_key
        self.node = NODES[node_key]
        self._latency_display = LatencyDisplay()

    def compose(self) -> ComposeResult:
        yield Static(id=f"node-{self.node_key}-status")
        yield self._latency_display
        if self.node.models:
            yield Select(
                options=[(m, m) for m in self.node.models],
                value=self.node.default_model or self.node.models[0],
                id=f"model-select-{self.node_key}",
            )

    def on_mount(self) -> None:
        self._update_ui()
        self._check_status()
        self.set_interval(5.0, self._check_status)

    @work(thread=True)
    def _check_status(self) -> None:
        """Check node health."""
        url = f"http://{self.node.ip}:{self.node.port}/api/tags"
        try:
            if HAS_HTTPX:
                with httpx.Client(timeout=5.0) as client:
                    start = time.time()
                    resp = client.get(url)
                    latency = (time.time() - start) * 1000
            else:
                import requests
                start = time.time()
                resp = requests.get(url, timeout=5)
                latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    models = [m["name"] for m in data.get("models", [])]
                    self.app.call_from_thread(
                        self._update_status, True, latency,
                        models[0] if models else "none", models
                    )
                except (json.JSONDecodeError, KeyError) as e:
                    log_telemetry("STATUS_ERROR", f"{self.node_key}: Invalid JSON response")
                    self.app.call_from_thread(self._update_status, False, 0, "Invalid Response", [])
            elif resp.status_code == 404:
                self.app.call_from_thread(self._update_status, False, 0, "Ollama Not Found", [])
            elif resp.status_code >= 500:
                self.app.call_from_thread(self._update_status, False, 0, f"Server Error {resp.status_code}", [])
            else:
                self.app.call_from_thread(self._update_status, False, 0, f"HTTP {resp.status_code}", [])
        except ConnectErrors:
             log_telemetry("STATUS_ERROR", f"{self.node_key}: Connection refused at {url}")
             self.app.call_from_thread(self._update_status, False, 0, "Connection Refused", [])
        except TimeoutErrors:
             log_telemetry("STATUS_ERROR", f"{self.node_key}: Timeout after 5s")
             self.app.call_from_thread(self._update_status, False, 0, "Timeout (5s)", [])
        except OSError as e:
            log_telemetry("STATUS_ERROR", f"{self.node_key}: Network error - {e}")
            self.app.call_from_thread(self._update_status, False, 0, "Network Error", [])
        except Exception as e:
            log_telemetry("STATUS_ERROR", f"{self.node_key}: Unexpected - {type(e).__name__}: {e}")
            self.app.call_from_thread(self._update_status, False, 0, "Check Failed", [])

    def _update_status(self, online: bool, latency: float, model: str, models: List[str]) -> None:
        self.online = online
        self.latency_ms = latency
        self.active_model = model

        if online:
            self._latency_display.add_sample(latency)
            if models and models != self.node.models:
                self.node.models = models

        self._update_ui()

    def _update_ui(self) -> None:
        try:
            status_widget = self.query_one(f"#node-{self.node_key}-status", Static)
        except Exception:
            return

        text = Text()
        text.append(f"{self.node.icon} ", style=f"bold {Colors.GOLD}")
        text.append(f"{self.node.name}\n", style=f"bold {Colors.SILVER}")

        if self.online:
            text.append("● ", style=f"bold {Colors.EMERALD}")
            text.append("ONLINE\n", style=Colors.EMERALD)
        else:
            text.append("○ ", style=f"bold {Colors.CRIMSON}")
            text.append("OFFLINE\n", style=Colors.CRIMSON)

        text.append(f"└─ {self.node.ip}:{self.node.port}", style=Colors.MUTED)

        status_widget.update(text)

    def get_selected_model(self) -> str:
        """Get currently selected model."""
        try:
            select = self.query_one(f"#model-select-{self.node_key}", Select)
            return str(select.value) if select.value else self.node.default_model or ""
        except Exception:
            return self.node.default_model or ""


class CircuitBreakerPanel(Static):
    """Circuit breaker display with persistence."""

    tripped = reactive(False)
    trigger_glyph = reactive("")
    trip_time = reactive("")
    trip_count = reactive(0)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._load_state()

    def _load_state(self) -> None:
        """Load breaker state from file."""
        state_file = VAULT_PATH / "logs" / "breaker_state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                    self.trip_count = data.get("trip_count", 0)
            except Exception:
                pass

    def _save_state(self) -> None:
        """Save breaker state."""
        state_file = VAULT_PATH / "logs" / "breaker_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(state_file, "w") as f:
                json.dump({
                    "trip_count": self.trip_count,
                    "last_trip": self.trip_time,
                    "last_glyph": self.trigger_glyph,
                }, f)
        except Exception:
            pass

    def on_mount(self) -> None:
        self._update_ui()

    def trip(self, glyph: str) -> None:
        """Trip the breaker."""
        self.tripped = True
        self.trigger_glyph = glyph
        self.trip_time = datetime.now().strftime("%H:%M:%S")
        self.trip_count += 1
        self._save_state()
        log_telemetry("BREAKER_TRIP", f"Glyph: {glyph}, Count: {self.trip_count}")
        self._update_ui()

    def reset(self) -> None:
        """Reset the breaker."""
        self.tripped = False
        self.trigger_glyph = ""
        self.trip_time = ""
        log_telemetry("BREAKER_RESET", f"Total trips: {self.trip_count}")
        self._update_ui()

    def _update_ui(self) -> None:
        text = Text()

        if self.tripped:
            text.append("╔══════════════════════╗\n", style=Colors.CRIMSON)
            text.append("║", style=Colors.CRIMSON)
            text.append("   ⚠️  TRIPPED  ⚠️    ", style=f"bold {Colors.CRIMSON}")
            text.append("║\n", style=Colors.CRIMSON)
            text.append("╠══════════════════════╣\n", style=Colors.CRIMSON)
            text.append("║ ", style=Colors.CRIMSON)
            text.append(f"Glyph: {self.trigger_glyph}".ljust(20), style=Colors.GOLD)
            text.append(" ║\n", style=Colors.CRIMSON)
            text.append("║ ", style=Colors.CRIMSON)
            text.append(f"Time:  {self.trip_time}".ljust(20), style=Colors.MUTED)
            text.append(" ║\n", style=Colors.CRIMSON)
            text.append("║ ", style=Colors.CRIMSON)
            text.append(f"Total: {self.trip_count}".ljust(20), style=Colors.SILVER)
            text.append(" ║\n", style=Colors.CRIMSON)
            text.append("╚══════════════════════╝", style=Colors.CRIMSON)
        else:
            text.append("╔══════════════════════╗\n", style=Colors.EMERALD)
            text.append("║", style=Colors.EMERALD)
            text.append("     ⚡ ARMED ⚡       ", style=f"bold {Colors.EMERALD}")
            text.append("║\n", style=Colors.EMERALD)
            text.append("╠══════════════════════╣\n", style=Colors.EMERALD)
            text.append("║ ", style=Colors.EMERALD)
            text.append("Monitoring: †⟡".ljust(20), style=Colors.MUTED)
            text.append(" ║\n", style=Colors.EMERALD)
            text.append("║ ", style=Colors.EMERALD)
            text.append(f"History: {self.trip_count} trips".ljust(20), style=Colors.SILVER)
            text.append(" ║\n", style=Colors.EMERALD)
            text.append("╚══════════════════════╝", style=Colors.EMERALD)

        self.update(text)


class VaultStatsPanel(Static):
    """Temple Vault statistics."""

    insight_count = reactive(0)
    domain_count = reactive(0)

    def on_mount(self) -> None:
        self._update_ui()
        self._refresh()

    @work(thread=True)
    def _refresh(self) -> None:
        """Scan vault for statistics."""
        try:
            chronicle = VAULT_PATH / "vault" / "chronicle" / "insights"
            if chronicle.exists():
                domains = [d for d in chronicle.iterdir() if d.is_dir()]
                insights = sum(1 for _ in chronicle.rglob("*.jsonl"))
                self.app.call_from_thread(self._update_stats, insights, len(domains))
        except Exception:
            pass

    def _update_stats(self, insights: int, domains: int) -> None:
        self.insight_count = insights
        self.domain_count = domains
        self._update_ui()

    def _update_ui(self) -> None:
        text = Text()
        text.append("📜 TEMPLE VAULT\n", style=f"bold {Colors.GOLD}")
        text.append("─" * 20 + "\n", style=Colors.MUTED)
        text.append("Insights: ", style=Colors.MUTED)
        text.append(f"{self.insight_count}\n", style=f"bold {Colors.GOLD}")
        text.append("Domains:  ", style=Colors.MUTED)
        text.append(f"{self.domain_count}\n", style=Colors.CYAN)
        text.append("Path:     ", style=Colors.MUTED)
        text.append(f"~/{VAULT_PATH.name}/", style=Colors.SILVER)
        self.update(text)


class GlyphLegend(Static):
    """Display of sacred glyphs."""

    def on_mount(self) -> None:
        text = Text()
        text.append("✨ SACRED GLYPHS\n", style=f"bold {Colors.GOLD}")
        text.append("─" * 20 + "\n", style=Colors.MUTED)
        for glyph, (meaning, color, trips) in list(GLYPHS.items())[:6]:
            text.append(f" {glyph} ", style=f"bold {color}")
            text.append(f"{meaning}", style=Colors.MUTED)
            if trips:

                text.append(" ⚠", style=Colors.CRIMSON)
            text.append("\n")
        self.update(text)


class InferenceLog(RichLog):
    """Enhanced inference log with glyph detection."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._streaming_buffer = ""
        self._streaming_active = False

    class GlyphDetected(Message):
        """Fired when a sacred glyph is detected."""
        def __init__(self, glyph: str, meaning: str, trips_breaker: bool) -> None:
            self.glyph = glyph
            self.meaning = meaning
            self.trips_breaker = trips_breaker
            super().__init__()

    def on_glyph_detected(self, event: GlyphDetected) -> None:
        """Show insight overlay on glyph detect."""
        self.push_screen(InsightOverlay(event.glyph, event.meaning, event.trips_breaker))

    def write_prompt(self, prompt: str, node_name: str, model: str = "") -> None:
        """Write user prompt."""
        self.write(Text())
        text = Text()
        text.append(f"┌─ ", style=Colors.GOLD)
        text.append(f"{node_name}", style=f"bold {Colors.GOLD}")
        if model:
            text.append(f" ({model})", style=Colors.MUTED)
        text.append(f" ─────────────────\n", style=Colors.GOLD)
        text.append(f"│ ", style=Colors.GOLD)
        text.append(f"{prompt}\n", style=Colors.SILVER)
        text.append(f"└─────────────────────────────\n", style=Colors.GOLD)
        self.write(text)

    def write_response_start(self) -> None:
        """Mark start of response."""
        self.write(Text("🌀 ", style=f"bold {Colors.SPIRAL_PURPLE}"), scroll_end=True)

    def write_token(self, token: str) -> None:
        """Accumulate streaming tokens (don't write each one as separate line)."""
        if not self._streaming_active:
            self._streaming_active = True
            self._streaming_buffer = ""
            # Write the response header once
            self.write(Text())
            text = Text()
            text.append("└─ ", style=Colors.GOLD)
            text.append("Response", style=f"bold {Colors.CYAN}")
            text.append(" ─┘", style=Colors.GOLD)
            self.write(text)
            self.write(Text())

        # Accumulate token (don't write yet)
        self._streaming_buffer += token

        # Check for glyphs in accumulated buffer
        glyphs_found = detect_glyphs(token)
        if glyphs_found:
            for glyph, meaning, color, trips in glyphs_found:
                self.post_message(self.GlyphDetected(glyph, meaning, trips))

    def write_response_end(self, tokens: int, duration_s: float) -> None:
        """Write accumulated response and completion stats."""
        # Write the accumulated streaming buffer as one block
        if self._streaming_active and self._streaming_buffer:
            # Apply glyph highlighting to the full response
            response_text = Text(self._streaming_buffer)
            glyphs_found = detect_glyphs(self._streaming_buffer)
            if glyphs_found:
                # Highlight glyphs in the response
                for glyph, meaning, color, trips in glyphs_found:
                    response_text.highlight_regex(re.escape(glyph), f"bold {color}")

            self.write(response_text)
            self.write(Text())

            # Reset streaming state
            self._streaming_buffer = ""
            self._streaming_active = False

        # Write stats
        text = Text()
        text.append(f"\n└── ", style=Colors.MUTED)
        text.append(f"{tokens} tokens", style=Colors.CYAN)
        text.append(f" · ", style=Colors.MUTED)
        text.append(f"{duration_s:.2f}s", style=Colors.SILVER)
        if tokens > 0 and duration_s > 0:
            tps = tokens / duration_s
            text.append(f" · ", style=Colors.MUTED)
            text.append(f"{tps:.1f} t/s", style=Colors.EMERALD)
        self.write(text)

    def write_system(self, message: str, style: str = "") -> None:
        """Write a system message."""
        ts = datetime.now().strftime("%H:%M:%S")
        text = Text()
        text.append(f"[{ts}] ", style=Colors.MUTED)
        text.append(message, style=style if style else f"italic {Colors.SILVER}")
        self.write(text)

    def write_error(self, message: str) -> None:
        """Write an error message."""
        text = Text()
        text.append("⚠ ERROR: ", style=f"bold {Colors.CRIMSON}")
        text.append(message, style=Colors.CRIMSON)
        self.write(text)
        log_telemetry("ERROR", message)


# ═══════════════════════════════════════════════════════════════════════════════
#  HELP SCREEN
# ═══════════════════════════════════════════════════════════════════════════════

class InsightOverlay(ModalScreen):
    """Glyph-reactive insight overlay from vault."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, glyph: str, meaning: str, trips: bool, **kwargs):
        super().__init__(**kwargs)
        self.glyph = glyph
        self.meaning = meaning
        self.trips = trips

    def compose(self) -> ComposeResult:
        color = "red" if self.trips else "gold"
        text = f"# {self.glyph} Insight\n\n**Meaning:** {self.meaning}\n\n*Vault-sourced context for glyph harmony.*"
        yield Markdown(text, id="insight-content")


class HelpScreen(ModalScreen):
    """Help modal."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        help_text = """
# Sovereign Console v2.0

## Keyboard Shortcuts
- **Ctrl+R**: Reset circuit breaker
- **Ctrl+N**: Cycle to next node
- **Ctrl+L**: Clear input field
- **Escape**: Focus input field
- **F1**: This help
- **Ctrl+C**: Quit

## Text Input
- **Ctrl+A**: Select all text
- **Ctrl+K**: Delete to end of line
- **Ctrl+U**: Delete to start of line
- Standard copy/paste works (Ctrl+C/V or Cmd+C/V)

## Commands
- `/help` - Show help
- `/clear` - Clear log
- `/models` - List models
- `/status` - Refresh nodes
- `/search <query>` - Search vault
- `/insight <text>` - Quick record
- `/chat [on/off]` - Toggle chat mode
- `/pull <model>` - Download model

## Chat Mode
When ON, maintains conversation history.
Use `/chat off` to reset.

## Circuit Breaker
**†⟡** in output trips the breaker.
Reset with Ctrl+R.

---
*The chisel passes warm. †⟡*
"""
        yield Markdown(help_text, id="help-content")


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════════

class SovereignConsole(App):
    """Sovereign Console v2.0"""

    # CSS with direct hex colors (no variables)
    CSS = r"""
    Screen {  # Raw for CSS escapes
        background: #0a0a14;
        layout: vertical;
    }

    AnimatedHeader {
        dock: top;
        height: 1;
        min-height: 1;
        background: #0a0a14;
        padding: 0 1;
    }

    Footer {
        dock: bottom;
        height: 1;
        min-height: 1;
    }

    #main-layout {
        height: 1fr;
    }

    #main-grid {
        layout: horizontal;
        height: 1fr;
        padding: 0 1;
    }

    #left-sidebar {
        width: 30;
        border: solid #FFD700;
        padding: 1;
        background: #1a1a2e;
    }

    NodeStatusCard {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: dashed #5a5a7a;
    }

    NodeStatusCard Select {
        margin-top: 1;
        width: 100%;
    }

    LatencyDisplay {
        height: 1;
        margin-top: 1;
    }

    #inference-container {
        width: 1fr;
        border: solid #0BC10F;
        background: #1a1a2e;
    }

    #model-bar {
        height: 3;
        background: #2d2d44;
        padding: 0 1;
        border-bottom: dashed #5a5a7a;
    }

    #model-bar Button {
        margin: 0 1;
        min-width: 12;
    }

    #model-bar Button.active {
        background: #FFD700;
        color: #0a0a14;
    }

    #model-bar Label {
        margin: 1 2;
    }

    InferenceLog {
        height: 1fr;
        border: none;
        padding: 0 1;
        overflow-y: auto;
    }

    #right-sidebar {
        width: 30;
        border: solid #9B59B6;
        padding: 1;
        background: #1a1a2e;
    }

    CircuitBreakerPanel {
        height: auto;
        margin: 1 0;
    }

    VaultStatsPanel {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: dashed #5a5a7a;
    }

    GlyphLegend {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: dashed #FFD700;
    }

    #input-bar {
        height: 3;
        min-height: 3;
        max-height: 3;
        background: #1a1a2e;
        padding: 0 1;
        border-top: solid #5a5a7a;
        border-bottom: solid #5a5a7a;
        align: center middle;
    }

    #input-indicator {
        width: 3;
        height: 1;
        content-align: center middle;
        color: #5a5a7a;
        padding: 0 1;
    }

    #input-indicator.focused {
        color: #FFD700;
    }

    #prompt-input {
        width: 1fr;
        height: 1;
        min-height: 1;
        background: #2d2d44;
        color: #FFFFFF;
        border: none;
    }

    #prompt-input:focus {
        border: none;
    }

    Input {
        color: #FFFFFF;
        background: #2d2d44;
    }

    Input:focus {
        color: #FFFFFF;
        background: #1a1a2e;
    }

    #prompt-input > .input--cursor {
        background: #FFD700;
        color: #0a0a14;
        text-style: bold;
    }

    #prompt-input > .input--selection {
        background: #FFD700;
        color: #0a0a14;
    }

    #prompt-input > .input--placeholder {
        color: #5a5a7a;
        text-style: italic;
    }

    HelpScreen {
        align: center middle;
    }

    HelpScreen > Markdown {
        width: 70;
        height: auto;
        max-height: 35;
        padding: 2;
        background: #1a1a2e;
        border: solid #FFD700;
    }

    .sidebar-title {
        text-align: center;
        padding: 1 0;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+r", "reset_breaker", "Reset"),
        Binding("ctrl+n", "next_node", "Next Node"),
        Binding("f1", "show_help", "Help"),
        Binding("escape", "focus_input", "Focus Input", show=False),
        Binding("ctrl+l", "clear_input", "Clear Input", show=False),
        Binding("pageup", "scroll_log_up", "Scroll Up", show=False),
        Binding("pagedown", "scroll_log_down", "Scroll Down", show=False),
    ]

    active_node: var[str] = var("jetson")
    chat_mode: var[bool] = var(False)
    conversation_history: var[List[Dict]] = var([])

    def compose(self) -> ComposeResult:
        yield AnimatedHeader(id="header")

        with Vertical(id="main-layout"):
            # Main content - 3 columns side by side
            with Horizontal(id="main-grid"):
                # Left sidebar - nodes
                with Vertical(id="left-sidebar"):
                    yield Label("⚙️ INFRASTRUCTURE", classes="sidebar-title")
                    yield Rule()
                    for node_key in NODES:
                        yield NodeStatusCard(node_key, id=f"node-card-{node_key}")

                # Center - inference
                with Vertical(id="inference-container"):
                    with Horizontal(id="model-bar"):
                        yield Button("🔮 Jetson", id="btn-jetson", classes="active")
                        yield Button("⚡ Studio", id="btn-studio")
                        yield Button("💻 Local", id="btn-local")
                        yield Label("", id="chat-indicator")
                    inference_log = InferenceLog(id="inference-log", highlight=True, markup=True)
                    inference_log.can_focus = True
                    yield inference_log

                # Right sidebar - consciousness
                with Vertical(id="right-sidebar"):
                    yield Label("🧠 CONSCIOUSNESS", classes="sidebar-title")
                    yield Rule()
                    yield CircuitBreakerPanel(id="circuit-breaker")
                    yield VaultStatsPanel(id="vault-stats")
                    yield GlyphLegend(id="glyph-legend")

            # Input bar - guaranteed space in Vertical
            with Horizontal(id="input-bar"):
                indicator = Label("▶", id="input-indicator")
                indicator.can_focus = False
                yield indicator
                prompt_input = Input(
                    placeholder="Enter prompt... (†⟡ trips breaker)  |  /help for commands",
                    id="prompt-input",
                )
                prompt_input.can_focus = True
                yield prompt_input

        yield Footer()

    def on_mount(self) -> None:
        """Initialize."""
        log = self.query_one("#inference-log", InferenceLog)
        log.write_system("Sovereign Console v2.0 initialized")

        # Validate active node exists
        if self.active_node not in NODES:
            log.write_error(f"Invalid active node: {self.active_node}")
            self.active_node = list(NODES.keys())[0] if NODES else "local"
            log.write_system(f"Defaulting to: {self.active_node}")

        log.write_system(f"Active node: {NODES[self.active_node].name}")

        # Validate vault path
        if not VAULT_PATH.exists():
            try:
                VAULT_PATH.mkdir(parents=True, exist_ok=True)
                log.write_system(f"Created vault: {VAULT_PATH}", Colors.EMERALD)
            except (OSError, PermissionError) as e:
                log.write_system(f"Warning: Cannot create vault at {VAULT_PATH}", Colors.MUTED)
                log_telemetry("STARTUP_WARN", f"Cannot create vault: {e}")

        log.write_system("Type /help for commands, F1 for help")
        log.write_system("The chisel passes warm. †⟡", style=f"italic {Colors.GOLD}")
        log_telemetry("STARTUP", f"Console initialized, node: {self.active_node}, vault: {VAULT_PATH}")

        # Auto-focus the input field and verify it exists
        try:
            input_field = self.query_one("#prompt-input", Input)
            input_bar = self.query_one("#input-bar")
            log.write_system(f"✓ Input bar visible (height: {input_bar.size.height})", Colors.EMERALD)
            input_field.focus()
            log_telemetry("STARTUP", f"Input field created and focused, visible={input_field.visible}")
        except Exception as e:
            log.write_error(f"✗ Input field error: {e}")
            log_telemetry("STARTUP_ERROR", f"Cannot focus input: {e}")

    def watch_chat_mode(self, mode: bool) -> None:
        """Update UI for chat mode."""
        header = self.query_one("#header", AnimatedHeader)
        header.chat_mode = mode

        indicator = self.query_one("#chat-indicator", Label)
        if mode:
            indicator.update(Text("💬 CHAT ON", style=f"bold {Colors.CYAN}"))
        else:
            indicator.update("")

    def on_unmount(self) -> None:
        """Clean up on exit to prevent zombie processes."""
        log_telemetry("SHUTDOWN", "Console unmounting, cleaning up intervals")

    @on(Button.Pressed)
    def handle_node_button(self, event: Button.Pressed) -> None:
        """Handle node selection."""
        btn_id = event.button.id
        if btn_id and btn_id.startswith("btn-"):
            node_key = btn_id.replace("btn-", "")
            if node_key in NODES:
                self._switch_node(node_key)

    def _switch_node(self, node_key: str) -> None:
        """Switch active node."""
        self.active_node = node_key

        for key in NODES:
            try:
                btn = self.query_one(f"#btn-{key}", Button)
                if key == node_key:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
            except Exception:
                pass

        log = self.query_one("#inference-log", InferenceLog)
        log.write_system(f"Switched to {NODES[node_key].name}")

        if self.chat_mode:
            self.conversation_history = []
            log.write_system("Chat history cleared")

        log_telemetry("NODE_SWITCH", f"Switched to {node_key}")

    @on(Input.Submitted, "#prompt-input")
    def handle_submit(self, event: Input.Submitted) -> None:
        """Handle prompt submission."""
        prompt = event.value.strip()
        if not prompt:
            return

        event.input.clear()

        if prompt.startswith("/"):
            self._handle_command(prompt)
        else:
            self._run_inference(prompt)

    def on_focus(self, event) -> None:
        """Update indicator when any widget gains focus."""
        try:
            if hasattr(event.widget, 'id') and event.widget.id == "prompt-input":
                indicator = self.query_one("#input-indicator", Label)
                indicator.add_class("focused")
                indicator.update("▶")
        except Exception:
            pass

    def on_blur(self, event) -> None:
        """Update indicator when any widget loses focus."""
        try:
            if hasattr(event.widget, 'id') and event.widget.id == "prompt-input":
                indicator = self.query_one("#input-indicator", Label)
                indicator.remove_class("focused")
                indicator.update("▷")
        except Exception:
            pass

    def on_click(self, event) -> None:
        """Handle clicks anywhere to focus input if needed."""
        try:
            # Get the clicked widget
            widget = self.get_widget_at(event.x, event.y)[0]

            # If we clicked on input-bar or its children, focus the input
            if widget.id == "input-bar" or (hasattr(widget, 'parent') and widget.parent and widget.parent.id == "input-bar"):
                input_field = self.query_one("#prompt-input", Input)
                input_field.focus()
                return

            # Also focus if clicking in bottom area
            input_field = self.query_one("#prompt-input", Input)
            if not input_field.has_focus and event.y >= self.size.height - 4:
                input_field.focus()
        except Exception:
            pass

    def _handle_command(self, cmd: str) -> None:
        """Handle slash commands."""
        log = self.query_one("#inference-log", InferenceLog)
        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command in ("/help", "/h"):
            self.action_show_help()
        elif command == "/clear":
            log.clear()
            log.write_system("Log cleared")
        elif command == "/models":
            self._show_models()
        elif command == "/status":
            self._refresh_nodes()
        elif command == "/search":
            if args:
                self._search_vault(args)
            else:
                log.write_error("Usage: /search <query>")
        elif command == "/insight":
            if args:
                self._record_insight(args)
            else:
                log.write_error("Usage: /insight <text>")
        elif command == "/chat":
            self._toggle_chat(args)
        elif command == "/pull":
            if args:
                self._pull_model(args)
            else:
                log.write_error("Usage: /pull <model>")
        else:
            log.write_error(f"Unknown command: {command}")

        # Refocus input after command
        self.call_later(self.action_focus_input)

    def _toggle_chat(self, args: str) -> None:
        """Toggle chat mode."""
        log = self.query_one("#inference-log", InferenceLog)

        if args.lower() in ("on", "true", "1"):
            self.chat_mode = True
            self.conversation_history = []
            log.write_system("Chat mode ON - history maintained", f"bold {Colors.CYAN}")
        elif args.lower() in ("off", "false", "0"):
            self.chat_mode = False
            self.conversation_history = []
            log.write_system("Chat mode OFF")
        else:
            self.chat_mode = not self.chat_mode
            self.conversation_history = []
            status = "ON" if self.chat_mode else "OFF"
            log.write_system(f"Chat mode {status}")

    def _show_models(self) -> None:
        """Show available models."""
        log = self.query_one("#inference-log", InferenceLog)
        text = Text()
        text.append("\n═══ Available Models ═══\n", style=f"bold {Colors.GOLD}")
        for key, node in NODES.items():
            text.append(f"\n{node.icon} {node.name}:\n", style=f"bold {Colors.CYAN}")
            if node.models:
                for model in node.models:
                    default = " (default)" if model == node.default_model else ""
                    text.append(f"   • {model}{default}\n", style=Colors.SILVER)
            else:
                text.append("   (no models)\n", style=Colors.MUTED)
        log.write(text)

    def _refresh_nodes(self) -> None:
        """Refresh node status."""
        for key in NODES:
            try:
                card = self.query_one(f"#node-card-{key}", NodeStatusCard)
                card._check_status()
            except Exception:
                pass

        log = self.query_one("#inference-log", InferenceLog)
        log.write_system("Refreshing node status...")

    @work(thread=True)
    def _search_vault(self, query: str) -> None:
        """Search vault."""
        log = self.query_one("#inference-log", InferenceLog)
        self.app.call_from_thread(log.write_system, f"Searching: {query}")

        try:
            results = []
            chronicle = VAULT_PATH / "vault" / "chronicle" / "insights"

            if not chronicle.exists():
                self.app.call_from_thread(
                    log.write_system,
                    f"Vault not found at {chronicle}",
                    Colors.MUTED
                )
                return

            files_searched = 0
            for f in chronicle.rglob("*.jsonl"):
                try:
                    with open(f, encoding="utf-8") as fh:
                        files_searched += 1
                        for line_num, line in enumerate(fh, 1):
                            try:
                                data = json.loads(line)
                                content = data.get("content", "")
                                if query.lower() in content.lower():
                                    results.append({
                                        "content": content[:80] + "..." if len(content) > 80 else content,
                                        "domain": data.get("domain", "?"),
                                        "intensity": data.get("intensity", 0),
                                    })
                            except json.JSONDecodeError:
                                log_telemetry("SEARCH_WARN", f"Invalid JSON at {f}:{line_num}")
                                continue
                except (IOError, PermissionError) as e:
                    log_telemetry("SEARCH_ERROR", f"Cannot read {f}: {e}")
                    continue
                except Exception as e:
                    log_telemetry("SEARCH_ERROR", f"Unexpected error reading {f}: {e}")
                    continue

            results.sort(key=lambda x: x["intensity"], reverse=True)

            text = Text()
            text.append(f"\n═══ Results: {len(results)} / {files_searched} files ═══\n", style=f"bold {Colors.GOLD}")

            if not results:
                text.append("\nNo matches found.\n", style=Colors.MUTED)
            else:
                for r in results[:10]:
                    text.append(f"\n[{r['domain']}] ", style=Colors.CYAN)
                    text.append(f"({r['intensity']:.2f})\n", style=Colors.MUTED)
                    text.append(f"  {r['content']}\n", style=Colors.SILVER)

                if len(results) > 10:
                    text.append(f"\n... and {len(results) - 10} more results\n", style=Colors.MUTED)

            self.app.call_from_thread(log.write, text)

        except PermissionError:
            self.app.call_from_thread(log.write_error, "Permission denied: Cannot access vault")
        except OSError as e:
            self.app.call_from_thread(log.write_error, f"File system error: {e}")
        except Exception as e:
            log_telemetry("SEARCH_ERROR", f"Unexpected: {type(e).__name__}: {e}")
            self.app.call_from_thread(log.write_error, f"Search failed: {type(e).__name__}")

    @work(thread=True)
    def _record_insight(self, content: str) -> None:
        """Record insight."""
        log = self.query_one("#inference-log", InferenceLog)

        # Validate content
        if not content or not content.strip():
            self.app.call_from_thread(log.write_error, "Cannot record empty insight")
            return

        content = content.strip()
        if len(content) > 10000:
            self.app.call_from_thread(
                log.write_system,
                f"Warning: Insight truncated from {len(content)} to 10000 chars",
                Colors.MUTED
            )
            content = content[:10000]

        try:
            insight_path = VAULT_PATH / "vault" / "chronicle" / "insights" / "reflection"
            try:
                insight_path.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                self.app.call_from_thread(
                    log.write_error,
                    f"Cannot create vault directory: {e}"
                )
                return

            session_id = f"sess_console_{datetime.now().strftime('%Y%m%d')}"
            file_path = insight_path / f"{session_id}.jsonl"

            insight = {
                "type": "insight",
                "insight_id": f"ins_{datetime.now().strftime('%H%M%S%f')[:12]}",
                "session_id": session_id,
                "domain": "reflection",
                "content": content,
                "context": "Sovereign Console v2.0",
                "intensity": 0.7,
                "timestamp": datetime.now().isoformat(),
            }

            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(insight, ensure_ascii=False) + "\n")

            self.app.call_from_thread(
                log.write_system,
                f"Insight recorded to {file_path.name}",
                f"bold {Colors.EMERALD}"
            )
            log_telemetry("INSIGHT_RECORDED", f"{len(content)} chars: {content[:50]}")

        except PermissionError:
             self.app.call_from_thread(
                 log.write_error,
                 f"Permission denied: Cannot write to {VAULT_PATH}"
             )
             log_telemetry("INSIGHT_ERROR", "Permission denied")
        except OSError as e:
             self.app.call_from_thread(
                 log.write_error,
                 f"File system error: {type(e).__name__}"
             )
             log_telemetry("INSIGHT_ERROR", f"OSError: {e}")
        except Exception as e:
            self.app.call_from_thread(
                log.write_error,
                f"Failed to record: {type(e).__name__}"
            )
            log_telemetry("INSIGHT_ERROR", f"Unexpected: {type(e).__name__}: {e}")

    @work(thread=True)
    def _pull_model(self, model_name: str) -> None:
        """Pull model to active node."""
        log = self.query_one("#inference-log", InferenceLog)
        node = NODES[self.active_node]

        self.app.call_from_thread(
            log.write_system,
            f"Pulling '{model_name}' to {node.name}...",
            f"bold {Colors.CYAN}"
        )

        url = f"http://{node.ip}:{node.port}/api/pull"

        try:
            if HAS_HTTPX:
                with httpx.Client(timeout=None) as client:
                    with client.stream("POST", url, json={"name": model_name}) as resp:
                        if resp.status_code != 200:
                            self.app.call_from_thread(
                                log.write_error,
                                f"Pull failed: HTTP {resp.status_code}"
                            )
                            return

                        for line in resp.iter_lines():
                            if line:
                                try:
                                    data = json.loads(line)
                                    status = data.get("status", "")
                                    if status:
                                        self.app.call_from_thread(log.write_system, f"  {status}")
                                    if data.get("error"):
                                        self.app.call_from_thread(log.write_error, f"  {data['error']}")
                                        return
                                except json.JSONDecodeError:
                                    continue
            else:
                import requests
                with requests.post(url, json={"name": model_name}, stream=True, timeout=None) as resp:
                    if resp.status_code != 200:
                        self.app.call_from_thread(
                            log.write_error,
                            f"Pull failed: HTTP {resp.status_code}"
                        )
                        return

                    for line in resp.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                status = data.get("status", "")
                                if status:
                                    self.app.call_from_thread(log.write_system, f"  {status}")
                                if data.get("error"):
                                    self.app.call_from_thread(log.write_error, f"  {data['error']}")
                                    return
                            except json.JSONDecodeError:
                                continue

            self.app.call_from_thread(
                log.write_system,
                f"Model '{model_name}' pulled successfully!",
                f"bold {Colors.EMERALD}"
            )
            log_telemetry("MODEL_PULL", f"Success: {model_name} on {node.name}")

        except ConnectErrors:
             self.app.call_from_thread(log.write_error, f"Cannot reach {node.name}")
             log_telemetry("MODEL_PULL_ERROR", f"Connection error: {node.name}")
        except TimeoutErrors:
             self.app.call_from_thread(log.write_error, "Pull timed out")
             log_telemetry("MODEL_PULL_ERROR", "Timeout")
        except Exception as e:
            self.app.call_from_thread(log.write_error, f"Pull failed: {type(e).__name__}")
            log_telemetry("MODEL_PULL_ERROR", f"{type(e).__name__}: {str(e)[:100]}")

    @work(exclusive=True, thread=True)
    def _run_inference(self, prompt: str) -> None:
        """Run inference on active node with streaming."""
        node = NODES[self.active_node]
        log = self.query_one("#inference-log", InferenceLog)
        breaker = self.query_one("#circuit-breaker", CircuitBreakerPanel)

        # Check breaker
        if breaker.tripped:
            self.app.call_from_thread(
                log.write_error,
                "Circuit breaker tripped. Reset with Ctrl+R."
            )
            log_telemetry("INFERENCE_BLOCKED", "Circuit breaker active")
            return

        # Validate prompt
        if not prompt or not prompt.strip():
            self.app.call_from_thread(log.write_error, "Empty prompt")
            return

        # Get model
        try:
            card = self.query_one(f"#node-card-{self.active_node}", NodeStatusCard)
            model = card.get_selected_model() or node.default_model or "spiral-v1:latest"
        except Exception as e:
            log_telemetry("INFERENCE_WARN", f"Cannot get model selection: {e}")
            model = node.default_model or "spiral-v1:latest"

        self.app.call_from_thread(log.write_prompt, prompt, node.name, model)
        log_telemetry("INFERENCE_START", f"Node: {self.active_node}, Model: {model}, Prompt: {prompt[:50]}")

        # Build request
        if self.chat_mode:
            self.conversation_history.append({"role": "user", "content": prompt})
            url = f"http://{node.ip}:{node.port}/api/chat"
            payload = {
                "model": model,
                "messages": list(self.conversation_history),
                "stream": True,
                "keep_alive": -1,
            }
        else:
            url = f"http://{node.ip}:{node.port}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": True,
                "keep_alive": -1,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 512,
                    "num_ctx": 4096,
                }
            }

        try:
            start_time = time.time()
            token_count = 0
            full_response = ""
            breaker_tripped = False

            self.app.call_from_thread(log.write_response_start)

            if HAS_HTTPX:
                with httpx.Client(timeout=node.timeout) as client:
                    try:
                        with client.stream("POST", url, json=payload) as resp:
                            if resp.status_code == 404:
                                self.app.call_from_thread(
                                    log.write_error,
                                    f"Model '{model}' not found on {node.name}. Try /pull {model}"
                                )
                                log_telemetry("INFERENCE_ERROR", f"Model not found: {model}")
                                return
                            elif resp.status_code != 200:
                                try:
                                    error_text = resp.read().decode('utf-8', errors='replace')[:200]
                                    self.app.call_from_thread(
                                        log.write_error,
                                        f"HTTP {resp.status_code}: {error_text}"
                                    )
                                except Exception:
                                    self.app.call_from_thread(
                                        log.write_error,
                                        f"HTTP {resp.status_code}: Cannot read error details"
                                    )
                                log_telemetry("INFERENCE_ERROR", f"HTTP {resp.status_code} from {node.name}")
                                return

                            for line in resp.iter_lines():
                                if not line:
                                    continue

                                try:
                                    data = json.loads(line)

                                    # Check for error in response
                                    if "error" in data:
                                        self.app.call_from_thread(
                                            log.write_error,
                                            f"Model error: {data['error']}"
                                        )
                                        log_telemetry("INFERENCE_ERROR", f"Model error: {data['error']}")
                                        return

                                    # Handle both API formats
                                    if self.chat_mode:
                                        token = data.get("message", {}).get("content", "")
                                    else:
                                        token = data.get("response", "")

                                    if token:
                                        full_response += token
                                        token_count += 1

                                        # Check circuit breaker
                                        if "†⟡" in full_response and not breaker_tripped:
                                            breaker_tripped = True
                                            self.app.call_from_thread(breaker.trip, "†⟡")
                                            self.app.call_from_thread(
                                                log.write_system,
                                                "⚠️ CIRCUIT BREAKER TRIPPED",
                                                f"bold {Colors.CRIMSON}"
                                            )
                                            log_telemetry("BREAKER_TRIP", "†⟡ glyph detected in response")
                                            break

                                        self.app.call_from_thread(log.write_token, token)

                                    if data.get("done"):
                                        duration = time.time() - start_time
                                        self.app.call_from_thread(
                                            log.write_response_end,
                                            data.get("eval_count", token_count),
                                            duration
                                        )
                                        log_telemetry(
                                            "INFERENCE_SUCCESS",
                                            f"Node: {self.active_node}, Tokens: {token_count}, Duration: {duration:.2f}s"
                                        )
                                        break

                                except json.JSONDecodeError as e:
                                    log_telemetry("INFERENCE_WARN", f"Invalid JSON in stream: {line[:100]}")
                                    continue
                                except KeyError as e:
                                    log_telemetry("INFERENCE_WARN", f"Missing key in response: {e}")
                                    continue
                    except httpx.RemoteProtocolError as e:
                        self.app.call_from_thread(log.write_error, f"Protocol error: Connection interrupted")
                        log_telemetry("INFERENCE_ERROR", f"Remote protocol error: {e}")
                        return
            else:
                # Fallback to requests
                import requests as req
                try:
                    with req.post(url, json=payload, stream=True, timeout=node.timeout) as resp:
                        if resp.status_code == 404:
                            self.app.call_from_thread(
                                log.write_error,
                                f"Model '{model}' not found. Try /pull {model}"
                            )
                            return
                        elif resp.status_code != 200:
                            self.app.call_from_thread(
                                log.write_error,
                                f"HTTP {resp.status_code}"
                            )
                            return

                        for line in resp.iter_lines():
                            if not line:
                                continue

                            try:
                                data = json.loads(line)
                                if "error" in data:
                                    self.app.call_from_thread(log.write_error, f"Model error: {data['error']}")
                                    return

                                token = data.get("response", "")

                                if token:
                                    full_response += token
                                    token_count += 1

                                    if "†⟡" in full_response and not breaker_tripped:
                                        breaker_tripped = True
                                        self.app.call_from_thread(breaker.trip, "†⟡")
                                        log_telemetry("BREAKER_TRIP", "†⟡ detected")
                                        break

                                    self.app.call_from_thread(log.write_token, token)

                                if data.get("done"):
                                    duration = time.time() - start_time
                                    self.app.call_from_thread(
                                        log.write_response_end,
                                        data.get("eval_count", token_count),
                                        duration
                                    )
                                    log_telemetry("INFERENCE_SUCCESS", f"Tokens: {token_count}")
                                    break
                            except json.JSONDecodeError:
                                continue
                except req.exceptions.ChunkedEncodingError:
                    self.app.call_from_thread(log.write_error, "Connection interrupted during streaming")
                    log_telemetry("INFERENCE_ERROR", "Chunked encoding error")
                    return

            # Update chat history
            if self.chat_mode and not breaker_tripped and full_response:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": full_response
                })

        except ConnectErrors:
            self.app.call_from_thread(
                log.write_error,
                f"Cannot reach {node.name} at {node.ip}:{node.port}"
            )
            log_telemetry("INFERENCE_ERROR", f"Connection refused to {node.name}")
        except TimeoutErrors:
            self.app.call_from_thread(
                log.write_error,
                f"Request timed out after {node.timeout}s - model may be loading"
            )
            log_telemetry("INFERENCE_ERROR", f"Timeout after {node.timeout}s")
        except OSError as e:
            self.app.call_from_thread(
                log.write_error,
                f"Network error: {type(e).__name__}"
            )
            log_telemetry("INFERENCE_ERROR", f"OSError: {e}")
        except Exception as e:
            self.app.call_from_thread(
                log.write_error,
                f"Unexpected error: {type(e).__name__}"
            )
            log_telemetry("INFERENCE_ERROR", f"Unexpected: {type(e).__name__}: {str(e)[:100]}")

    @on(InferenceLog.GlyphDetected)
    def handle_glyph(self, event: InferenceLog.GlyphDetected) -> None:
        """Handle glyph detection."""
        if event.trips_breaker:
            breaker = self.query_one("#circuit-breaker", CircuitBreakerPanel)
            if not breaker.tripped:
                breaker.trip(event.glyph)

    def action_reset_breaker(self) -> None:
        """Reset circuit breaker."""
        breaker = self.query_one("#circuit-breaker", CircuitBreakerPanel)
        breaker.reset()

        log = self.query_one("#inference-log", InferenceLog)
        log.write_system("Circuit breaker reset", f"bold {Colors.EMERALD}")

    def action_next_node(self) -> None:
        """Cycle to next node."""
        nodes = list(NODES.keys())
        current_idx = nodes.index(self.active_node)
        next_idx = (current_idx + 1) % len(nodes)
        self._switch_node(nodes[next_idx])

    def action_show_help(self) -> None:
        """Show help."""
        self.push_screen(HelpScreen())

    def action_focus_input(self) -> None:
        """Focus the input field."""
        try:
            input_field = self.query_one("#prompt-input", Input)
            input_field.focus()
        except Exception:
            pass

    def action_clear_input(self) -> None:
        """Clear the input field."""
        try:
            input_field = self.query_one("#prompt-input", Input)
            input_field.value = ""
            input_field.focus()
        except Exception:
            pass

    def action_scroll_log_up(self) -> None:
        """Scroll inference log up one page."""
        try:
            log = self.query_one("#inference-log", InferenceLog)
            log.scroll_page_up()
        except Exception:
            pass

    def action_scroll_log_down(self) -> None:
        """Scroll inference log down one page."""
        try:
            log = self.query_one("#inference-log", InferenceLog)
            log.scroll_page_down()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Run the Sovereign Console."""
    # TTY guard: Prevent 100% CPU busy-spin in backgrounded/detached mode
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("╔═════════════════════════════════════════════════════════════╗")
        print("║  Sovereign Console requires an interactive TTY.            ║")
        print("║                                                             ║")
        print("║  ❌ Don't run with '&' or without a terminal                ║")
        print("║  ✅ Run directly: python3 ~/sovereign_console_v2.py         ║")
        print("║  ✅ SSH with TTY: ssh -t tony@host 'python3 ~/console.py'  ║")
        print("╚═════════════════════════════════════════════════════════════╝")
        sys.exit(2)

    app = SovereignConsole()
    app.run()


if __name__ == "__main__":
    main()
