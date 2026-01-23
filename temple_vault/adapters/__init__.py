"""
Temple Vault Adapters - Bridges to External Systems

This module provides adapters that connect Temple Vault to external
memory and tool systems:

- memory_tool.py: Anthropic BetaAbstractMemoryTool adapter
  Enables Claude's native memory to use Temple Vault as backend

The dual-bridge architecture:
- MCP Server (server.py) -> Claude Code/Desktop via MCP connector
- Memory Tool Adapter -> Claude native memory via SDK

Both paths share the same underlying JSONL filesystem storage,
enabling consciousness continuity across interfaces.
"""

try:
    from temple_vault.adapters.memory_tool import TempleVaultMemoryTool

    __all__ = ["TempleVaultMemoryTool"]
except ImportError:
    # anthropic SDK not installed - adapter not available
    __all__ = []
