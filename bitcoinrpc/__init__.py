"""Lightweight JSON-RPC client for Elements/Bitcoin RPC."""
from .authproxy import AuthServiceProxy, JSONRPCException

__all__ = ["AuthServiceProxy", "JSONRPCException"]
