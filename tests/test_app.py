from pathlib import Path

from client.rpc import call
from server.app import create_app
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


def test_staging_vide_au_demarrage(vault):
    (vault / ".staging").mkdir()
    (vault / ".staging" / "reste.bin").write_bytes(b"x")
    create_app(vault)
    assert not any((vault / ".staging").iterdir())


def test_main_refuse_coffre_inexistant(tmp_path):
    import subprocess, sys
    r = subprocess.run([sys.executable, "-m", "server.app", "--vault", str(tmp_path / "absent")],
                       capture_output=True, text=True, timeout=30, cwd=Path(__file__).parent.parent)
    assert r.returncode != 0 and "absent" in r.stderr and not (tmp_path / "absent").exists()
