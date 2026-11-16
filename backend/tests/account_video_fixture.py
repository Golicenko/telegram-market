"""Generate a real, tiny 30s WebM for decoding/seeking tests, never a user video."""

import os
from io import BytesIO
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw


def make_video(directory):
    ffmpeg = os.environ.get("FFMPEG_BINARY") or shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("Real media test requires ffmpeg (installed in CI)")
    image = Image.new("RGB", (320, 180), "#0b1929")
    draw = ImageDraw.Draw(image)
    draw.rectangle((30, 65, 270, 125), fill="#e6a13c")
    draw.ellipse((60, 105, 95, 140), fill="#14283f")
    draw.ellipse((210, 105, 245, 140), fill="#14283f")
    draw.text((30, 20), "ISOLATED VIDEO TEST - NOT A LISTING", fill="white")
    frame = BytesIO()
    image.save(frame, format="JPEG")
    target = directory / "account-preview.webm"
    result = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-framerate",
            "10",
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            "libvpx",
            "-b:v",
            "100k",
            "-y",
            str(target),
        ],
        input=frame.getvalue() * 300,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return target
