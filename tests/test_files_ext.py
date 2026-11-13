import inspect

import pytest
from pydantic import ValidationError

from client.rpc import call
from conftest import client, running
from server.app import create_server
from server.digest import Sha256Stream, digest_obj, sha256_b64url
from server.files_ext import X_MCP_FILE, FileInput, accepts


@pytest.fixture
async def http_echo(vault, monkeypatch):
    """Serveur avec l'outil de test `_echo_upload_required` (jamais en production).

    Un outil MCPServer ne peut pas renvoyer un résultat `upload_required` brut :
    l'intercepteur de l'extension court-circuite l'appel, comme le fera le Task 6.
    """
    server = create_server(vault)

    @server.tool()
    def _echo_upload_required() -> str:
        raise AssertionError("court-circuité par l'intercepteur")

    ext = server._extensions[0]
    original = ext.intercept_tool_call

    async def echo(params, ctx, call_next):
        if params.name != "_echo_upload_required":
            return await original(params, ctx, call_next)
        state = (ctx.params or {}).get("requestState")
        if state is None:
            return {"resultType": "upload_required", "uploads": [], "requestState": "plain-42"}
        return {"resultType": "complete", "content": [{"type": "text", "text": state}]}

    monkeypatch.setattr(ext, "intercept_tool_call", echo)
    async with running(server.streamable_http_app()) as app, client(app) as c:
        yield c


def test_seal_existe_encore():
    # casse si le SDK change l'API privée dont on dépend
    from mcp.server.request_state import RequestStateBoundary

    assert list(inspect.signature(RequestStateBoundary._seal).parameters)[:3] == ["self", "ctx", "state"]


async def test_upload_required_scelle_puis_relance(http_echo):
    r1 = await call(http_echo, "tools/call", {"name": "_echo_upload_required", "arguments": {}}, {"upload"})
    assert r1["result"]["resultType"] == "upload_required"
    sealed = r1["result"]["requestState"]
    assert sealed != "plain-42"
    r2 = await call(
        http_echo,
        "tools/call",
        {"name": "_echo_upload_required", "arguments": {}, "requestState": sealed},
        {"upload"},
    )
    assert r2["result"]["content"][0]["text"] == "plain-42"


async def test_etat_trafique_refuse(http_echo):
    r = await call(
        http_echo,
        "tools/call",
        {"name": "_echo_upload_required", "arguments": {}, "requestState": "plain-42"},
        {"upload"},
    )
    assert r["error"]["code"] == -32602


async def test_outil_fichier_cache_sans_upload(http):
    sans = await call(http, "tools/list", {})
    avec = await call(http, "tools/list", {}, {"upload"})
    noms = lambda r: {t["name"] for t in r["result"]["tools"]}
    assert "vault_import_file" not in noms(sans) and "vault_import_file" in noms(avec)
    assert "vault_import_base64" in noms(sans)


async def test_schema_vault_import_file(http):
    r = await call(http, "tools/list", {}, {"upload"})
    schema = next(t for t in r["result"]["tools"] if t["name"] == "vault_import_file")["inputSchema"]
    file = schema["properties"]["file"]
    assert file["x-mcp-file"] == X_MCP_FILE
    file_input = schema["$defs"][file["$ref"].rsplit("/", 1)[-1]]
    assert {"id", "mimeType", "size", "digest"} <= set(file_input["required"])
    assert "name" not in file_input["required"] and "data" not in file_input["required"]
    digest = schema["$defs"][file_input["properties"]["digest"]["$ref"].rsplit("/", 1)[-1]]
    assert set(digest["required"]) == {"algorithm", "value"}
    assert digest["properties"]["algorithm"]["const"] == "sha-256"


def test_digest_objet():
    d = digest_obj(b"abc")
    assert d == {"algorithm": "sha-256", "value": sha256_b64url(b"abc")}
    s = Sha256Stream()
    s.update(b"abc")
    assert s.digest_obj() == d
    base = {"id": "f1", "mimeType": "application/pdf", "size": 3}
    assert FileInput(**base, digest=d).digest.value == d["value"]
    for bad in ({**d, "algorithm": "md5"}, d["value"]):
        with pytest.raises(ValidationError):
            FileInput(**base, digest=bad)


@pytest.mark.parametrize(
    "name,mime,ok",
    [
        ("a.pdf", "application/pdf", True),
        ("a.png", "image/png", True),
        ("a.md", "text/plain", True),
        ("a.exe", "application/octet-stream", False),
    ],
)
def test_accepts(name, mime, ok):
    assert accepts(name, mime, X_MCP_FILE["accept"]) is ok
