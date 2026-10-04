"""HTTP attachments of the console: bytes sent with a Content-Disposition the browser saves under the given name."""

from __future__ import annotations

from urllib.parse import quote

from fastapi.responses import Response


def content_disposition(filename: str) -> str:
    """RFC 6266: a plain quoted name when it is URL-safe ASCII, ``filename*=utf-8''…`` otherwise (accents, quotes)."""
    quoted = quote(filename)
    return f"attachment; filename*=utf-8''{quoted}" if quoted != filename else f'attachment; filename="{filename}"'


def attachment(data: bytes, filename: str, media_type: str) -> Response:
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": content_disposition(filename)})
