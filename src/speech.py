"""Speech-to-text with Amazon Transcribe streaming (no S3).

Used for the voice-over of uploaded Media Compliance videos and for video posts collected
by a scan. The media is never stored:

  1. ffmpeg writes the upload to a temporary directory inside the task and extracts the
     audio as 16 kHz mono 16-bit PCM; the directory is deleted as soon as the audio is read.
  2. The PCM is streamed to Amazon Transcribe in small chunks. With more than one entry in
     transcription.language_options (de-CH, fr-FR, it-IT, en-US by default) Transcribe
     identifies the spoken language itself; if language identification is rejected, the
     stream is retried in transcription.preferred_language.
  3. The final (non-partial) results are joined into one transcript.

Credentials come from the ECS task role (the awscrt default credential chain).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import threading

from .config import aws_region
from .netsafe import FFMPEG_INPUT_SAFETY

log = logging.getLogger(__name__)

_SAMPLE_RATE = 16000
_CHUNK = 8192                       # ~0.25 s of 16 kHz 16-bit mono audio per event


def to_pcm(file_bytes: bytes, filename: str) -> bytes | None:
    """16 kHz mono s16le PCM of the media's audio track, or None (no ffmpeg / no audio)."""
    if not shutil.which("ffmpeg"):
        log.warning("ffmpeg not found — cannot extract audio for transcription")
        return None
    with tempfile.TemporaryDirectory() as td:
        src = os.path.join(td, os.path.basename(filename or "media.mp4") or "media.mp4")
        out = os.path.join(td, "audio.raw")
        with open(src, "wb") as fh:
            fh.write(file_bytes)
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *FFMPEG_INPUT_SAFETY, "-i", src, "-vn", "-ac", "1",
               "-ar", str(_SAMPLE_RATE), "-f", "s16le", "-acodec", "pcm_s16le", out]
        try:
            subprocess.run(cmd, capture_output=True, timeout=300)
        except Exception as exc:  # noqa: BLE001
            log.warning("ffmpeg audio extraction failed: %s", exc)
            return None
        if not os.path.exists(out) or os.path.getsize(out) < _SAMPLE_RATE:  # < 0.5 s of audio
            return None
        with open(out, "rb") as fh:
            return fh.read()


async def _stream(pcm: bytes, region: str, languages: list[str], preferred: str, speed: float) -> str:
    from amazon_transcribe.client import TranscribeStreamingClient
    from amazon_transcribe.model import TranscriptEvent

    client = TranscribeStreamingClient(region=region)
    kwargs: dict = {"media_sample_rate_hz": _SAMPLE_RATE, "media_encoding": "pcm"}
    if len(languages) > 1:
        kwargs.update(language_code=None, identify_language=True,
                      language_options=languages, preferred_language=preferred or languages[0])
    else:
        kwargs["language_code"] = languages[0] if languages else preferred
    stream = await client.start_stream_transcription(**kwargs)

    parts: list[str] = []
    # Pace the upload at `speed` x real time (0 = as fast as possible).
    pause = (_CHUNK / (2 * _SAMPLE_RATE)) / speed if speed > 0 else 0.0

    async def write() -> None:
        for i in range(0, len(pcm), _CHUNK):
            await stream.input_stream.send_audio_event(audio_chunk=pcm[i:i + _CHUNK])
            if pause:
                await asyncio.sleep(pause)
        await stream.input_stream.end_stream()

    async def read() -> None:
        async for event in stream.output_stream:
            if isinstance(event, TranscriptEvent):
                for result in event.transcript.results or []:
                    if not result.is_partial and result.alternatives:
                        text = (result.alternatives[0].transcript or "").strip()
                        if text:
                            parts.append(text)

    await asyncio.gather(write(), read())
    return " ".join(parts).strip()


def _run(coro) -> str:
    """Run a coroutine to completion from sync code, even if this thread has a loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    box: dict = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    t.join()
    if "error" in box:
        raise box["error"]
    return box.get("value", "")


def transcribe_aws(file_bytes: bytes, filename: str, cfg: dict) -> str:
    """Transcript of a video/audio file's speech via Amazon Transcribe ('' when silent)."""
    pcm = to_pcm(file_bytes, filename)
    if not pcm:
        return ""
    t = cfg.get("transcription", {})
    languages = [str(x) for x in t.get("language_options", ["de-CH", "fr-FR", "it-IT", "en-US"]) if x]
    preferred = str(t.get("preferred_language", "de-CH"))
    speed = float(t.get("stream_speed", 8))
    region = aws_region(cfg)
    try:
        return _run(_stream(pcm, region, languages, preferred, speed))
    except Exception as exc:  # noqa: BLE001
        if len(languages) > 1:
            log.warning("Transcribe language identification failed (%s); retrying in %s", exc, preferred)
            try:
                return _run(_stream(pcm, region, [preferred], preferred, speed))
            except Exception as exc2:  # noqa: BLE001
                exc = exc2
        log.warning("Amazon Transcribe failed: %s", exc)
        return ""
