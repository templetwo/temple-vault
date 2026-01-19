#!/usr/bin/env python3
"""
Temple Vault MCP Server - MCPB Entry Point

This is the entry point for the MCPB (MCP Bundle) package.
It runs the Temple Vault MCP server in stdio mode for Claude Desktop.

Usage:
    Double-click the .mcpb file to install in Claude Desktop
    Or: python main.py --vault ~/TempleVault
"""

import sys
import os

# Ensure the server directory is in path (for local temple_vault package)
server_dir = os.path.dirname(os.path.abspath(__file__))
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from temple_vault.server import main

if __name__ == "__main__":
    main()
