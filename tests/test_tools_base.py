import json

from client.rpc import call


async def test_search_et_read(http, vault):
    (vault / "00 - Inbox" / "a.md").write_text("Police Desjardins habitation")
    r = await call(http, "tools/call", {"name": "vault_search", "arguments": {"query": "desjardins"}})
    assert "00 - Inbox/a.md" in json.dumps(r["result"])
    r = await call(http, "tools/call", {"name": "vault_read_note", "arguments": {"chemin": "00 - Inbox/a.md"}})
    assert "Desjardins" in r["result"]["content"][0]["text"]


async def test_read_hors_coffre(http):
    r = await call(http, "tools/call", {"name": "vault_read_note", "arguments": {"chemin": "../x.md"}})
    assert r["result"]["isError"] is True


async def test_read_absent(http):
    r = await call(http, "tools/call", {"name": "vault_read_note", "arguments": {"chemin": "nope.md"}})
    assert r["result"]["isError"] is True


async def test_search_ignore_caches_et_limite(http, vault):
    for d in (".staging", ".obsidian", "00 - Inbox/.cache"):
        (vault / d).mkdir(parents=True, exist_ok=True)
        (vault / d / "x.md").write_text("secret mot")
    for i in range(3):
        (vault / f"n{i}.md").write_text("x" * 300 + " mot " + "y" * 300)
    r = await call(http, "tools/call", {"name": "vault_search", "arguments": {"query": "MOT", "limit": 2}})
    items = r["result"]["structuredContent"]["result"]
    assert len(items) == 2
    assert all(len(i["extrait"]) <= 160 and "mot" in i["extrait"] for i in items)
    r = await call(http, "tools/call", {"name": "vault_search", "arguments": {"query": "secret"}})
    assert r["result"]["structuredContent"]["result"] == []
