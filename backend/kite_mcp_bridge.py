"""
Kite MCP Bridge - Uses Kite MCP tools directly via a subprocess approach.
This file is called by the Claude Code harness which has Kite MCP connected.
It reads commands from stdin and writes JSON responses to stdout.
The FastAPI server in kite_bridge_mcp_server.py calls this as a subprocess.

Usage: python kite_mcp_bridge.py <command> [args]
Commands:
  ltp NSE:INFY
  ohlc NSE:INFY
  historical NSE:INFY day 2024-01-01 2024-12-31
  search INFY
"""
import sys
import json

# This module is meant to be imported by the MCP-aware runtime.
# When running standalone, it returns empty data.
# The actual MCP calls happen via the FastAPI route handlers that call
# the Kite MCP tools through the harness.

def get_empty_response():
    return {}
