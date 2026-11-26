"""Integrações locais do Open Structural Analysis."""

from .claude_code import ClaudeCodeIntegration
from .mcp_local import LocalMcpIntegration

__all__ = ["ClaudeCodeIntegration", "LocalMcpIntegration"]
