import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.api.routes.exports import OpenFileResponse


class ClientGone(Exception):
    pass


async def _receive() -> dict[str, Any]:
    # A client that stays connected: Starlette listens for a disconnect
    # while streaming, so this must wait instead of returning at once.
    await asyncio.Event().wait()
    return {"type": "http.disconnect"}


def _serve(response: OpenFileResponse, fail_on: str | None) -> list[str]:
    sent: list[str] = []

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == fail_on:
            raise ClientGone
        sent.append(message["type"])

    scope = {"type": "http", "asgi": {"spec_version": "2.3"}, "method": "GET"}
    asyncio.run(response(scope, _receive, send))  # type: ignore[arg-type]
    return sent


@pytest.mark.parametrize("fail_on", ["http.response.start", "http.response.body"])
def test_file_is_closed_when_the_client_disconnects(
    tmp_path: Path, fail_on: str
) -> None:
    file = tmp_path / "export.csv"
    file.write_bytes(b"x" * 200_000)
    handle = file.open("rb")

    with pytest.raises(ClientGone):
        _serve(OpenFileResponse(handle, media_type="text/csv"), fail_on)

    assert handle.closed


def test_file_is_streamed_in_full_and_closed(tmp_path: Path) -> None:
    file = tmp_path / "export.csv"
    file.write_bytes(b"x" * 200_000)
    handle = file.open("rb")
    response = OpenFileResponse(handle, media_type="text/csv")

    sent = _serve(response, None)

    assert sent[0] == "http.response.start" and sent.count("http.response.body") >= 2
    assert response.headers["content-length"] == "200000"
    assert handle.closed
