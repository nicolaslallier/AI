from typing import Any

from mcp.server.extension import Extension

EXT_ID = "io.modelcontextprotocol/files"
MAX_INLINE = 1048576


class FilesExtension(Extension):
    identifier = EXT_ID

    def settings(self) -> dict[str, Any]:
        return {"upload": {}, "download": {}, "maxInlineBytes": MAX_INLINE}
