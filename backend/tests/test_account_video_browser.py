"""Local real HTTP/filesystem/browser on SQLite, no production mutations."""

import asyncio
import os
import socket
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.responses import HTMLResponse

from account_video_fixture import make_video
from test_account_video_volume import (
    video_app as video_app,
    account_db as account_db,
    configuration as configuration,
    upload,
)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("RUN_ACCOUNT_VIDEO_BROWSER") != "1",
    reason="Dedicated real media browser step",
)
async def test_real_volume_video_player(request, tmp_path):
    app, _, _, _ = request.getfixturevalue("video_app")
    file = make_video(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        video, result = await upload(client, file.read_bytes(), "video/webm")
        assert result.status_code == 200, result.text
    await run_browser(app, video["id"])


async def run_browser(app, video_id, auth=""):
    @app.get("/account-video-test")
    async def fixture_page():
        return HTMLResponse(
            '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        )

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    process = None
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.02)
        process = await asyncio.create_subprocess_exec(
            os.environ.get("NODE_BINARY", "node"),
            str(
                Path(__file__).resolve().parents[2]
                / "webapp/tests/account-video-browser.cjs"
            ),
            env={
                **os.environ,
                "ACCOUNT_VIDEO_TEST_URL": f"http://127.0.0.1:{listener.getsockname()[1]}",
                "ACCOUNT_VIDEO_TEST_ID": str(video_id),
                "ACCOUNT_VIDEO_TEST_AUTH": auth,
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        output, _ = await asyncio.wait_for(process.communicate(), 120)
        assert process.returncode == 0, output.decode(errors="replace")
        print(output.decode(errors="replace"))
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()
        server.should_exit = True
        await task
        listener.close()
