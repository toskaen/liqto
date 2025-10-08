"""Minimal AuthServiceProxy implementation for Elements JSON-RPC."""
from __future__ import annotations

import base64
import itertools
import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional
from urllib import error, request


class JSONRPCException(RuntimeError):
    """Exception raised for JSON-RPC errors returned by the node."""

    def __init__(self, error: Dict[str, Any]):
        self.code = error.get("code")
        self.message = error.get("message", "Unknown error")
        super().__init__(f"RPC error {self.code}: {self.message}")


@dataclass
class _RPCMethod:
    """Callable proxy for a remote RPC method."""

    proxy: "AuthServiceProxy"
    method: str

    def __call__(self, *args: Any) -> Any:
        return self.proxy._call(self.method, args)


class AuthServiceProxy:
    """Lightweight drop-in replacement for python-bitcoinrpc's proxy."""

    def __init__(
        self,
        service_url: str,
        *,
        timeout: Optional[float] = 30.0,
    ) -> None:
        self._service_url = service_url
        self._timeout = timeout
        self._request_id = itertools.count(1)
        self._headers = {
            "Content-Type": "application/json",
        }

        # Extract credentials for basic auth
        if "@" in service_url and "//" in service_url:
            scheme, rest = service_url.split("//", 1)
            creds, endpoint = rest.split("@", 1)
            self._service_url = f"{scheme}//{endpoint}"
            self._headers["Authorization"] = "Basic " + base64.b64encode(
                creds.encode()
            ).decode()

    def __getattr__(self, name: str) -> _RPCMethod:
        if name.startswith("_"):
            raise AttributeError(name)
        return _RPCMethod(self, name)

    def batch(self, calls: Iterable[tuple[str, Iterable[Any]]]) -> list[Any]:
        """Execute a batch of RPC calls."""

        payload = [
            {
                "jsonrpc": "2.0",
                "id": next(self._request_id),
                "method": method,
                "params": list(params),
            }
            for method, params in calls
        ]
        data = self._post(json.dumps(payload).encode())
        result = json.loads(data.decode())
        if not isinstance(result, list):
            raise RuntimeError("Invalid batch response")
        return [self._extract_result(item) for item in result]

    def _call(self, method: str, params: Iterable[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._request_id),
            "method": method,
            "params": list(params),
        }
        data = self._post(json.dumps(payload).encode())
        result = json.loads(data.decode())
        return self._extract_result(result)

    def _post(self, payload: bytes) -> bytes:
        req = request.Request(self._service_url, data=payload, headers=self._headers)
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                return response.read()
        except error.HTTPError as http_err:
            # Elements returns JSON-RPC errors with HTTP 500 status codes. Parse the
            # body (when available) and surface it as a ``JSONRPCException`` so
            # callers receive the structured RPC error instead of a transport
            # level ``HTTPError``.
            body = http_err.read()
            message = body.decode(errors="replace") if body else http_err.reason
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                raise JSONRPCException({"code": http_err.code, "message": message}) from http_err

            if isinstance(data, dict) and data.get("error"):
                raise JSONRPCException(data["error"]) from http_err

            raise JSONRPCException({"code": http_err.code, "message": message}) from http_err

    def _extract_result(self, data: Dict[str, Any]) -> Any:
        if not isinstance(data, dict):
            raise RuntimeError("Invalid JSON-RPC response")
        if data.get("error"):
            raise JSONRPCException(data["error"])
        return data.get("result")

    def close(self) -> None:
        """Compatibility stub for context manager usage."""

    def __enter__(self) -> "AuthServiceProxy":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
