"""Leitor binário somente leitura, separado da tradução para o domínio OSA."""

from .core import LayoutError, Reader, load_stream
from .decode import extract

__all__ = ["LayoutError", "Reader", "extract", "load_stream"]
