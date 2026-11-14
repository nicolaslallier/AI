"""Enveloppe JSON-RPC sans état 2026-07-28, partagée par `mcpf` et les tests."""
import itertools
import json

import httpx
from mcp_types import CLIENT_CAPABILITIES_META_KEY, CLIENT_INFO_META_KEY, PROTOCOL_VERSION_META_KEY

VERSION = "2026-07-28"
EXT_ID = "io.modelcontextprotocol/files"
_ids = itertools.count(1)


async def call(http: httpx.AsyncClient, method: str, params: dict, caps: set[str] = frozenset()) -> dict:
    """Renvoie le message JSON-RPC complet (`result` ou `error`)."""
    meta = {
        PROTOCOL_VERSION_META_KEY: VERSION,
        CLIENT_INFO_META_KEY: {"name": "mcpf", "version": "0.1"},
        CLIENT_CAPABILITIES_META_KEY: {"extensions": {EXT_ID: {c: {} for c in caps}}} if caps else {},
    }
    body = {"jsonrpc": "2.0", "id": next(_ids), "method": method, "params": {**params, "_meta": meta}}
    headers = {"mcp-protocol-version": VERSION, "mcp-method": method, "accept": "application/json, text/event-stream"}
    if isinstance(name := params.get("name"), str) and method == "tools/call":
        headers["mcp-name"] = name  # ponytail: ASCII seulement ; encoder =?base64?...?= sinon
    r = await http.post("/mcp", json=body, headers=headers)
    if r.headers["content-type"].startswith("text/event-stream"):
        data = [l[6:] for l in r.text.splitlines() if l.startswith("data: ")]
        return json.loads(data[-1])
    return r.json()
