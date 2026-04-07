from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
from starlette.responses import StreamingResponse


def sse_iterator(resp: httpx.Response) -> AsyncIterator[bytes]:
    async def gen():
        try:
            async for chunk in resp.aiter_bytes():
                if chunk:
                    yield chunk
        finally:
            await resp.aclose()

    return gen()


def streaming_proxy_response(resp: httpx.Response, status_code: int) -> StreamingResponse:
    headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in ("transfer-encoding", "connection", "content-length", "server")
    }
    return StreamingResponse(
        sse_iterator(resp),
        status_code=status_code,
        headers=dict(headers),
        media_type=headers.get("content-type"),
    )
