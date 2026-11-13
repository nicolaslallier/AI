from client.rpc import call
from server.digest import Sha256Stream, sha256_b64url


async def test_annonce_extension(http):
    r = await call(http, "server/discover", {})
    ext = r["result"]["capabilities"]["extensions"]["io.modelcontextprotocol/files"]
    assert ext == {"upload": {}, "download": {}, "maxInlineBytes": 1048576}


def test_sha256_b64url():
    assert sha256_b64url(b"abc") == "ungWv48Bz-pBQUDeXa4iI7ADYaOWF3qctBD_YfIAFa0"
    s = Sha256Stream()
    s.update(b"a")
    s.update(b"bc")
    assert s.b64url() == sha256_b64url(b"abc")
