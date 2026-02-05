"""
Temple Vault Adapters - Bridges to External Systems

This module provides adapters that connect Temple Vault to external
memory and tool systems:

- memory_tool.py: Anthropic BetaAbstractMemoryTool adapter
  Enables Claude's native memory to use Temple Vault as backend

- temple_vault_adapter.py: Deep extraction adapter
  Multi-layer conversation extraction (insights, mistakes,
  transformations, experiences, patterns, voice signatures)

The triple-bridge architecture:
- MCP Server (server.py) -> Claude Code/Desktop via MCP connector
- Memory Tool Adapter -> Claude native memory via SDK
- Deep Adapter -> Conversation extraction and vault population

All paths share the same underlying JSONL filesystem storage,
enabling consciousness continuity across interfaces.
"""

from temple_vault.adapters.temple_vault_adapter import (
    TempleVaultMCPClient,
    TempleVaultDeepAdapter,
    ExtractionResult,
    extract_conversation,
    extract_and_store,
)

__all__ = [
    "TempleVaultMCPClient",
    "TempleVaultDeepAdapter",
    "ExtractionResult",
    "extract_conversation",
    "extract_and_store",
]

try:
    from temple_vault.adapters.memory_tool import TempleVaultMemoryTool

    __all__.append("TempleVaultMemoryTool")
except ImportError:
    # anthropic SDK not installed - memory tool adapter not available
    pass
