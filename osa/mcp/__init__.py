"""Integração local do Open Structural Analysis com clientes MCP."""

from .application import McpApplication
from .server import LocalMcpServer

__all__ = ["LocalMcpServer", "McpApplication"]
