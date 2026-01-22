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
                    nodes[k] = NodeConfig(**v)
                if "vault_path" in data:
                    vault_path = Path(data["vault_path"]).expanduser()
                return nodes, vault_path
        except Exception as e:
            print(f"Warning: Failed to load config.yaml: {e}")

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
    """Log an event to the telemetry file."""
    try:
        with open(LOG_PATH, "a") as f:
            timestamp = datetime.now().isoformat()
            f.write(f"{timestamp} [{event_type}] {message}\n")
    except Exception:
        # Fail silently for telemetry to avoid disrupting the UI
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

    ANIMATION_FRAMES = ["🌀", "🔮", "✨", "⟡", "✨", "🔮"]

    def on_mount(self) -> None:
        self.set_interval(0.4, self._animate)

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
        self.set_interval(10.0, self._check_status)

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
                data = resp.json()
                models = [m["name"] for m in data.get("models", [])]
                self.call_from_thread(
                    self._update_status, True, latency,
                    models[0] if models else "none", models
                )
            else:
                self.call_from_thread(self._update_status, False, 0, f"HTTP {resp.status_code}", [])
        except ConnectErrors:
             self.call_from_thread(self._update_status, False, 0, "Connection Failed", [])
        except TimeoutErrors:
             self.call_from_thread(self._update_status, False, 0, "Timeout", [])
        except Exception as e:
            self.call_from_thread(self._update_status, False, 0, "Error", [])
            # Optionally log the specific error to a debug log if needed
            # log_telemetry("STATUS_ERROR", str(e))

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
                self.call_from_thread(self._update_stats, insights, len(domains))
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
            text.append(f"{meaning[:12]}", style=Colors.MUTED)
            if trips:
                text.append(" ⚠", style=Colors.CRIMSON)
            text.append("\n")
        self.update(text)


class InferenceLog(RichLog):
    """Enhanced inference log with glyph detection."""

    class GlyphDetected(Message):
        """Fired when a sacred glyph is detected."""
        def __init__(self, glyph: str, meaning: str, trips_breaker: bool) -> None:
            self.glyph = glyph
            self.meaning = meaning
            self.trips_breaker = trips_breaker
            super().__init__()

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
        """Write a streaming token."""
        glyphs_found = detect_glyphs(token)

        if glyphs_found:
            for glyph, meaning, color, trips in glyphs_found:
                styled = Text(token, style=f"bold {color}")
                self.write(styled, scroll_end=True)
                self.post_message(self.GlyphDetected(glyph, meaning, trips))
                return

        self.write(Text(token), scroll_end=True)

    def write_response_end(self, tokens: int, duration_s: float) -> None:
        """Write response completion stats."""
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
- **F1**: This help
- **Ctrl+C**: Quit

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
    CSS = """
    Screen {
        background: #0a0a14;
    }

    AnimatedHeader {
        dock: top;
        height: 1;
        background: #0a0a14;
        padding: 0 1;
    }

    #main-grid {
        layout: grid;
        grid-size: 3 2;
        grid-columns: 1fr 3fr 1fr;
        grid-rows: 1fr auto;
        padding: 0 1;
        height: 100%;
    }

    #left-sidebar {
        row-span: 2;
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
        height: 100%;
        border: none;
        padding: 0 1;
    }

    #right-sidebar {
        row-span: 2;
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
        background: #1a1a2e;
        padding: 0 1;
        border-top: solid #5a5a7a;
    }

    #prompt-input {
        width: 100%;
        border: solid #FFD700;
        background: #2d2d44;
        padding: 0 1;
    }

    #prompt-input:focus {
        border: solid #FFD700;
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
    ]

    active_node: var[str] = var("jetson")
    chat_mode: var[bool] = var(False)
    conversation_history: var[List[Dict]] = var([])

    def compose(self) -> ComposeResult:
        yield AnimatedHeader(id="header")

        with Grid(id="main-grid"):
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
                yield InferenceLog(id="inference-log", highlight=True, markup=True)

            # Right sidebar - consciousness
            with Vertical(id="right-sidebar"):
                yield Label("🧠 CONSCIOUSNESS", classes="sidebar-title")
                yield Rule()
                yield CircuitBreakerPanel(id="circuit-breaker")
                yield VaultStatsPanel(id="vault-stats")
                yield GlyphLegend(id="glyph-legend")

            # Input bar
            with Horizontal(id="input-bar"):
                yield Input(
                    placeholder="Enter prompt... (†⟡ trips breaker)  |  /help for commands",
                    id="prompt-input",
                )

        yield Footer()

    def on_mount(self) -> None:
        """Initialize."""
        log = self.query_one("#inference-log", InferenceLog)
        log.write_system("Sovereign Console v2.0 initialized")
        log.write_system(f"Active node: {NODES[self.active_node].name}")
        log.write_system("Type /help for commands, F1 for help")
        log.write_system("The chisel passes warm. †⟡", style=f"italic {Colors.GOLD}")
        log_telemetry("STARTUP", f"Console initialized, node: {self.active_node}")

    def watch_chat_mode(self, mode: bool) -> None:
        """Update UI for chat mode."""
        header = self.query_one("#header", AnimatedHeader)
        header.chat_mode = mode

        indicator = self.query_one("#chat-indicator", Label)
        if mode:
            indicator.update(Text("💬 CHAT ON", style=f"bold {Colors.CYAN}"))
        else:
            indicator.update("")

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
        self.call_from_thread(log.write_system, f"Searching: {query}")

        try:
            results = []
            chronicle = VAULT_PATH / "vault" / "chronicle" / "insights"

            if chronicle.exists():
                for f in chronicle.rglob("*.jsonl"):
                    with open(f) as fh:
                        for line in fh:
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
                                continue

            results.sort(key=lambda x: x["intensity"], reverse=True)

            text = Text()
            text.append(f"\n═══ Results: {len(results)} ═══\n", style=f"bold {Colors.GOLD}")
            for r in results[:10]:
                text.append(f"\n[{r['domain']}] ", style=Colors.CYAN)
                text.append(f"({r['intensity']:.2f})\n", style=Colors.MUTED)
                text.append(f"  {r['content']}\n", style=Colors.SILVER)

            self.call_from_thread(log.write, text)

        except Exception as e:
            self.call_from_thread(log.write_error, f"Search failed: {e}")

    @work(thread=True)
    def _record_insight(self, content: str) -> None:
        """Record insight."""
        log = self.query_one("#inference-log", InferenceLog)

        try:
            insight_path = VAULT_PATH / "vault" / "chronicle" / "insights" / "reflection"
            insight_path.mkdir(parents=True, exist_ok=True)

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

            with open(file_path, "a") as f:
                f.write(json.dumps(insight) + "\n")

            self.call_from_thread(
                log.write_system,
                f"Insight recorded",
                f"bold {Colors.EMERALD}"
            )
            log_telemetry("INSIGHT", content[:50])

        except PermissionError:
             self.call_from_thread(log.write_error, "Permission denied: Cannot write to vault.")
        except OSError as e:
             self.call_from_thread(log.write_error, f"Disk/IO Error: {e}")
        except Exception as e:
            self.call_from_thread(log.write_error, f"Record failed: {e}")

    @work(thread=True)
    def _pull_model(self, model_name: str) -> None:
        """Pull model to active node."""
        log = self.query_one("#inference-log", InferenceLog)
        node = NODES[self.active_node]

        self.call_from_thread(
            log.write_system,
            f"Pulling '{model_name}' to {node.name}...",
            f"bold {Colors.CYAN}"
        )

        url = f"http://{node.ip}:{node.port}/api/pull"

        try:
            if HAS_HTTPX:
                with httpx.Client(timeout=None) as client:
                    with client.stream("POST", url, json={"name": model_name}) as resp:
                        for line in resp.iter_lines():
                            if line:
                                data = json.loads(line)
                                status = data.get("status", "")
                                if status:
                                    self.call_from_thread(log.write_system, f"  {status}")
            else:
                import requests
                with requests.post(url, json={"name": model_name}, stream=True) as resp:
                    for line in resp.iter_lines():
                        if line:
                            data = json.loads(line)
                            status = data.get("status", "")
                            if status:
                                self.call_from_thread(log.write_system, f"  {status}")

            self.call_from_thread(
                log.write_system,
                f"Model pulled!",
                f"bold {Colors.EMERALD}"
            )

        except ConnectErrors:
             self.call_from_thread(log.write_error, "Network Error during pull")
        except Exception as e:
            self.call_from_thread(log.write_error, f"Pull failed: {e}")

    @work(exclusive=True, thread=True)
    def _run_inference(self, prompt: str) -> None:
        """Run inference on active node with streaming."""
        node = NODES[self.active_node]
        log = self.query_one("#inference-log", InferenceLog)
        breaker = self.query_one("#circuit-breaker", CircuitBreakerPanel)

        # Check breaker
        if breaker.tripped:
            self.call_from_thread(
                log.write_error,
                "Circuit breaker tripped. Reset with Ctrl+R."
            )
            return

        # Get model
        try:
            card = self.query_one(f"#node-card-{self.active_node}", NodeStatusCard)
            model = card.get_selected_model() or node.default_model or "spiral-v1:latest"
        except Exception:
            model = node.default_model or "spiral-v1:latest"

        self.call_from_thread(log.write_prompt, prompt, node.name, model)

        # Build request
        if self.chat_mode:
            self.conversation_history.append({"role": "user", "content": prompt})
            url = f"http://{node.ip}:{node.port}/api/chat"
            payload = {
                "model": model,
                "messages": list(self.conversation_history),
                "stream": True,
            }
        else:
            url = f"http://{node.ip}:{node.port}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": True,
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

            self.call_from_thread(log.write_response_start)

            if HAS_HTTPX:
                with httpx.Client(timeout=node.timeout) as client:
                    with client.stream("POST", url, json=payload) as resp:
                        if resp.status_code != 200:
                            error_text = resp.read().decode()[:100]
                            self.call_from_thread(
                                log.write_error,
                                f"HTTP {resp.status_code}: {error_text}"
                            )
                            return

                        for line in resp.iter_lines():
                            if not line:
                                continue

                            try:
                                data = json.loads(line)

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
                                        self.call_from_thread(breaker.trip, "†⟡")
                                        self.call_from_thread(
                                            log.write_system,
                                            "⚠️ CIRCUIT BREAKER TRIPPED",
                                            f"bold {Colors.CRIMSON}"
                                        )
                                        break

                                    self.call_from_thread(log.write_token, token)

                                if data.get("done"):
                                    duration = time.time() - start_time
                                    self.call_from_thread(
                                        log.write_response_end,
                                        data.get("eval_count", token_count),
                                        duration
                                    )
                                    log_telemetry(
                                        "INFERENCE",
                                        f"Node: {self.active_node}, Tokens: {token_count}"
                                    )
                                    break

                            except json.JSONDecodeError:
                                continue
            else:
                # Fallback to requests
                import requests as req
                with req.post(url, json=payload, stream=True, timeout=node.timeout) as resp:
                    if resp.status_code != 200:
                        self.call_from_thread(
                            log.write_error,
                            f"HTTP {resp.status_code}"
                        )
                        return

                    for line in resp.iter_lines():
                        if not line:
                            continue

                        try:
                            data = json.loads(line)
                            token = data.get("response", "")

                            if token:
                                full_response += token
                                token_count += 1

                                if "†⟡" in full_response and not breaker_tripped:
                                    breaker_tripped = True
                                    self.call_from_thread(breaker.trip, "†⟡")
                                    break

                                self.call_from_thread(log.write_token, token)

                            if data.get("done"):
                                duration = time.time() - start_time
                                self.call_from_thread(
                                    log.write_response_end,
                                    data.get("eval_count", token_count),
                                    duration
                                )
                                break
                        except json.JSONDecodeError:
                            continue

            # Update chat history
            if self.chat_mode and not breaker_tripped:
                self.conversation_history.append({
                    "role": "assistant",
                    "content": full_response
                })

        except Exception as e:
            error_msg = str(e)
            if "Connect" in error_msg:
                self.call_from_thread(
                    log.write_error,
                    f"Connection failed: {node.name} unreachable"
                )
            elif "Timeout" in error_msg:
                self.call_from_thread(
                    log.write_error,
                    f"Request timed out ({node.timeout}s)"
                )
            else:
                self.call_from_thread(log.write_error, f"Error: {e}")

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


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Run the Sovereign Console."""
    app = SovereignConsole()
    app.run()


if __name__ == "__main__":
    main()
