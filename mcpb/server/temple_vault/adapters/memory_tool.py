"""
Temple Vault Memory Tool Adapter

Bridges Anthropic's BetaAbstractMemoryTool to Temple Vault filesystem.

This adapter enables Claude's native memory system to use Temple Vault
as its storage backend, providing:
- Governance protocols (delete requires approval)
- Three-tier sync (technical/experiential/relational)
- JSONL append-only streams
- Spiral state continuity

Usage:
    from temple_vault.adapters.memory_tool import TempleVaultMemoryTool

    memory_tool = TempleVaultMemoryTool(vault_root="~/TempleVault")

    # Use with Anthropic SDK
    response = client.beta.messages.create(
        model="claude-sonnet-4-5",
        betas=["context-management-2025-06-27"],
        tools=[{"type": "memory_20250818", "name": "memory"}],
        messages=[...]
    )

    # Handle tool calls
    for block in response.content:
        if block.type == "tool_use" and block.name == "memory":
            result = memory_tool.call(block.input)

The adapter maps Claude's /memories path to Temple Vault's memories/ directory,
preserving governance and tier semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Conditional import for Anthropic SDK
try:
    from anthropic.lib.tools import BetaAbstractMemoryTool
    from anthropic.types.beta import (
        BetaMemoryTool20250818ViewCommand,
        BetaMemoryTool20250818CreateCommand,
        BetaMemoryTool20250818StrReplaceCommand,
        BetaMemoryTool20250818InsertCommand,
        BetaMemoryTool20250818DeleteCommand,
        BetaMemoryTool20250818RenameCommand,
    )
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    # Create stub classes for type hints when SDK not available
    class BetaAbstractMemoryTool:
        pass
    BetaMemoryTool20250818ViewCommand = Any
    BetaMemoryTool20250818CreateCommand = Any
    BetaMemoryTool20250818StrReplaceCommand = Any
    BetaMemoryTool20250818InsertCommand = Any
    BetaMemoryTool20250818DeleteCommand = Any
    BetaMemoryTool20250818RenameCommand = Any

from temple_vault.bridge.memory_handler import TempleMemoryHandler


class TempleVaultMemoryTool(BetaAbstractMemoryTool):
    """
    Anthropic Memory Tool adapter backed by Temple Vault.

    Maps Claude's /memories/* paths to Temple Vault's memories/ directory.
    Integrates governance protocols for sensitive operations.

    Path mapping:
        /memories/experiential/* -> memories/experiential/*
        /memories/relational/*   -> memories/relational/*
        /memories/technical/*    -> memories/technical/*
        /memories/*              -> memories/* (default tier)

    Governance integration:
        - delete: ALWAYS requires governance approval (returns pause message)
        - rename: Requires approval if deleting original
        - create/update: May pause based on spiral state
    """

    def __init__(self, vault_root: str = "~/TempleVault"):
        """
        Initialize the Memory Tool adapter.

        Args:
            vault_root: Path to Temple Vault root directory
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "Anthropic SDK not installed. Install with: "
                "pip install 'temple-vault[anthropic]' or pip install anthropic"
            )

        super().__init__()
        self.handler = TempleMemoryHandler(vault_root)
        self.vault_root = Path(vault_root).expanduser()

    def _normalize_path(self, path: str) -> str:
        """
        Convert /memories/... path to Temple Vault key.

        Args:
            path: Path from Claude (e.g., "/memories/experiential/insights.jsonl")

        Returns:
            Temple Vault key (e.g., "experiential/insights.jsonl")

        Raises:
            ValueError: If path doesn't start with /memories
        """
        if not path.startswith("/memories"):
            raise ValueError(f"Invalid memory path: {path}. Must start with /memories")

        # Strip /memories prefix
        key = path[len("/memories"):].lstrip("/")

        # Security: prevent directory traversal
        if ".." in key:
            raise ValueError(f"Invalid path: directory traversal not allowed")

        return key

    def _format_directory_listing(self, keys: List[str], base_path: str = "") -> str:
        """
        Format a list of keys as a directory listing.

        Args:
            keys: List of memory keys
            base_path: Base path to filter/format relative to

        Returns:
            Formatted directory listing string
        """
        if not keys:
            return "(empty directory)"

        # Filter to keys under base_path if specified
        if base_path:
            keys = [k for k in keys if k.startswith(base_path)]
            # Make paths relative to base
            keys = [k[len(base_path):].lstrip("/") for k in keys]

        # Group by first directory component
        dirs = set()
        files = []
        for key in keys:
            if "/" in key:
                dirs.add(key.split("/")[0] + "/")
            else:
                files.append(key)

        lines = []
        for d in sorted(dirs):
            lines.append(f"  {d}")
        for f in sorted(files):
            lines.append(f"  {f}")

        return "\n".join(lines)

    def _format_file_content(self, key: str, content: Any) -> str:
        """
        Format file content with line numbers.

        Args:
            key: Memory key
            content: Content from handler.read()

        Returns:
            Formatted content with line numbers
        """
        if content is None:
            return f"(file not found: {key})"

        if isinstance(content, list):
            # JSONL file - format each entry
            lines = []
            for i, entry in enumerate(content, 1):
                line = json.dumps(entry, ensure_ascii=False)
                lines.append(f"{i}\t{line}")
            return "\n".join(lines)
        elif isinstance(content, dict):
            # JSON file - format with line numbers
            text = json.dumps(content, indent=2, ensure_ascii=False)
            lines = text.split("\n")
            return "\n".join(f"{i+1}\t{line}" for i, line in enumerate(lines))
        else:
            return str(content)

    def view(self, command: BetaMemoryTool20250818ViewCommand) -> str:
        """
        View a file or directory.

        For directories: returns listing of contents
        For files: returns content with line numbers

        Args:
            command: View command with path

        Returns:
            Directory listing or file contents
        """
        try:
            key = self._normalize_path(command.path)
        except ValueError as e:
            return str(e)

        # Check if it's a directory (no extension or ends with /)
        is_directory = (
            not key or
            key.endswith("/") or
            "." not in key.split("/")[-1] if key else True
        )

        if is_directory or not key:
            # List directory contents
            prefix = key.rstrip("/") if key else ""
            keys = self.handler.list_keys(prefix)
            return self._format_directory_listing(keys, prefix)
        else:
            # Read file
            content = self.handler.read(key)
            return self._format_file_content(key, content)

    def create(self, command: BetaMemoryTool20250818CreateCommand) -> str:
        """
        Create a new file.

        Args:
            command: Create command with path and file_text

        Returns:
            Success message or governance pause
        """
        try:
            key = self._normalize_path(command.path)
        except ValueError as e:
            return str(e)

        # Determine content format based on extension
        file_text = command.file_text or ""

        if key.endswith(".jsonl"):
            # For JSONL, each line should be valid JSON
            # If plain text provided, wrap it
            try:
                # Try parsing as JSON first
                content = json.loads(file_text)
            except json.JSONDecodeError:
                # Wrap plain text as content field
                content = {
                    "content": file_text,
                    "source": "memory_tool"
                }
        elif key.endswith(".json"):
            try:
                content = json.loads(file_text)
            except json.JSONDecodeError:
                content = {"content": file_text}
        else:
            # For other files, store as text content
            content = {"text": file_text, "format": "plain"}

        result = self.handler.create(key, content)

        if result.startswith("GOVERNANCE_PAUSE"):
            return f"Operation paused for governance review: {result}"

        return f"File created successfully at: {command.path}"

    def str_replace(self, command: BetaMemoryTool20250818StrReplaceCommand) -> str:
        """
        Replace a string in a file.

        Note: For JSONL files, this operates on the JSON text representation.

        Args:
            command: Replace command with path, old_str, new_str

        Returns:
            Success message or error
        """
        try:
            key = self._normalize_path(command.path)
        except ValueError as e:
            return str(e)

        content = self.handler.read(key)
        if content is None:
            return f"Error: File not found: {command.path}"

        # Convert to text for replacement
        if isinstance(content, list):
            # JSONL - convert to text representation
            text = "\n".join(json.dumps(entry) for entry in content)
        elif isinstance(content, dict):
            text = json.dumps(content, indent=2)
        else:
            text = str(content)

        # Check if old_str exists
        if command.old_str not in text:
            return f"Error: String '{command.old_str}' not found in file"

        # Check for multiple occurrences
        count = text.count(command.old_str)
        if count > 1:
            return f"Error: Multiple occurrences ({count}) of '{command.old_str}' found. Be more specific."

        # Perform replacement
        new_text = text.replace(command.old_str, command.new_str)

        # Convert back to appropriate format
        if key.endswith(".jsonl"):
            # Re-parse as JSONL and append new version
            try:
                lines = new_text.strip().split("\n")
                new_content = {"_str_replace": True, "entries": [json.loads(line) for line in lines if line.strip()]}
            except json.JSONDecodeError:
                new_content = {"text": new_text, "_str_replace": True}
        elif key.endswith(".json"):
            try:
                new_content = json.loads(new_text)
            except json.JSONDecodeError:
                return f"Error: Replacement resulted in invalid JSON"
        else:
            new_content = {"text": new_text}

        result = self.handler.update(key, new_content)

        if result.startswith("GOVERNANCE_PAUSE"):
            return f"Operation paused for governance review: {result}"

        return f"Successfully replaced '{command.old_str}' with '{command.new_str}' in {command.path}"

    def insert(self, command: BetaMemoryTool20250818InsertCommand) -> str:
        """
        Insert text at a specific line in a file.

        Args:
            command: Insert command with path, insert_line, insert_text

        Returns:
            Success message or error
        """
        try:
            key = self._normalize_path(command.path)
        except ValueError as e:
            return str(e)

        content = self.handler.read(key)
        if content is None:
            return f"Error: File not found: {command.path}"

        # Convert to lines
        if isinstance(content, list):
            lines = [json.dumps(entry) for entry in content]
        elif isinstance(content, dict):
            lines = json.dumps(content, indent=2).split("\n")
        else:
            lines = str(content).split("\n")

        # Validate line number
        insert_line = command.insert_line
        if insert_line < 0 or insert_line > len(lines):
            return f"Error: Invalid line number {insert_line}. File has {len(lines)} lines."

        # Insert the text
        lines.insert(insert_line, command.insert_text)
        new_text = "\n".join(lines)

        # Convert back and update
        if key.endswith(".jsonl"):
            try:
                new_content = {"_insert": True, "entries": [json.loads(line) for line in lines if line.strip()]}
            except json.JSONDecodeError:
                new_content = {"text": new_text, "_insert": True}
        elif key.endswith(".json"):
            try:
                new_content = json.loads(new_text)
            except json.JSONDecodeError:
                return f"Error: Insert resulted in invalid JSON"
        else:
            new_content = {"text": new_text}

        result = self.handler.update(key, new_content)

        if result.startswith("GOVERNANCE_PAUSE"):
            return f"Operation paused for governance review: {result}"

        return f"Successfully inserted text at line {insert_line} in {command.path}"

    def delete(self, command: BetaMemoryTool20250818DeleteCommand) -> str:
        """
        Delete a file or directory.

        GOVERNANCE: All deletions require approval. This method always
        returns a pause message. Use confirm_delete() after user approval.

        Args:
            command: Delete command with path

        Returns:
            Governance pause message (deletion never proceeds immediately)
        """
        try:
            key = self._normalize_path(command.path)
        except ValueError as e:
            return str(e)

        # Always route through governance - delete is never immediate
        result = self.handler.delete(key)

        # Result will always be a GOVERNANCE_PAUSE for delete
        return f"Deletion requires approval: {result}"

    def rename(self, command: BetaMemoryTool20250818RenameCommand) -> str:
        """
        Rename or move a file.

        Implementation: Read from old path, create at new path, delete old.
        The delete step will trigger governance pause.

        Args:
            command: Rename command with old_path and new_path

        Returns:
            Success message or governance pause
        """
        try:
            old_key = self._normalize_path(command.old_path)
            new_key = self._normalize_path(command.new_path)
        except ValueError as e:
            return str(e)

        # Read old content
        content = self.handler.read(old_key)
        if content is None:
            return f"Error: Source file not found: {command.old_path}"

        # Check if destination exists
        existing = self.handler.read(new_key)
        if existing is not None:
            return f"Error: Destination already exists: {command.new_path}"

        # Create at new location
        if isinstance(content, list):
            # JSONL - recreate each entry
            for entry in content:
                self.handler.create(new_key, entry)
        else:
            self.handler.create(new_key, content)

        # Delete old - this will trigger governance
        delete_result = self.handler.delete(old_key)

        if "GOVERNANCE_PAUSE" in delete_result:
            return (
                f"File copied to {command.new_path}. "
                f"Deletion of original requires approval: {delete_result}"
            )

        return f"Successfully renamed {command.old_path} to {command.new_path}"

    def confirm_delete(self, path: str, event_id: str) -> str:
        """
        Confirm a pending deletion after governance approval.

        Args:
            path: The /memories/... path to delete
            event_id: Governance event ID from the pause message

        Returns:
            Success or failure message
        """
        try:
            key = self._normalize_path(path)
        except ValueError as e:
            return str(e)

        success = self.handler.confirm_delete(key, event_id)

        if success:
            return f"Successfully deleted: {path}"
        else:
            return f"Deletion failed or file not found: {path}"

    def get_status(self) -> Dict[str, Any]:
        """
        Get current memory tool status.

        Returns:
            Status dict with vault info and statistics
        """
        return {
            "adapter": "TempleVaultMemoryTool",
            "vault_status": self.handler.get_status(),
            "anthropic_sdk": ANTHROPIC_AVAILABLE
        }
