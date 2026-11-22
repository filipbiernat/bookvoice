"""Speech synthesis with Microsoft Edge's online neural voices (via ``edge-tts``)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from pathlib import Path

import edge_tts

log = logging.getLogger(__name__)

#: Voice used when none is given, keyed by the book's primary language subtag.
DEFAULT_VOICES = {
    "cs": "cs-CZ-AntoninNeural",
    "de": "de-DE-ConradNeural",
    "en": "en-US-AndrewNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "it": "it-IT-DiegoNeural",
    "nl": "nl-NL-MaartenNeural",
    "pl": "pl-PL-MarekNeural",
    "pt": "pt-BR-AntonioNeural",
    "uk": "uk-UA-OstapNeural",
}
#: Multilingual voices can read most languages reasonably well.
FALLBACK_VOICE = "en-US-AndrewMultilingualNeural"


class TTSError(RuntimeError):
    """Raised when speech could not be synthesised."""


def default_voice(language: str) -> str:
    """Pick a sensible default voice for a BCP-47 language tag such as ``pl`` or ``en-GB``."""
    return DEFAULT_VOICES.get(language.split("-")[0].lower(), FALLBACK_VOICE)


async def list_voices(locale: str | None = None) -> list[dict]:
    """Return available voices, optionally filtered by locale prefix (e.g. ``pl`` or ``en-GB``)."""
    voices = await edge_tts.list_voices()
    if locale:
        prefix = locale.lower()
        voices = [v for v in voices if v["Locale"].lower().startswith(prefix)]
    return sorted(voices, key=lambda v: v["ShortName"])


async def synthesize(
    text: str, dst: Path, *, voice: str, rate: str = "+0%", attempts: int = 7
) -> None:
    """Synthesise ``text`` to the MP3 file ``dst``; existing non-empty files are kept.

    Transient failures (network errors, throttling, empty responses) are retried
    with a growing back-off.
    """
    if dst.exists() and dst.stat().st_size > 0:
        return
    tmp = dst.with_name(dst.name + ".part")
    for attempt in range(1, attempts + 1):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(tmp))
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise TTSError("received empty audio")
            tmp.replace(dst)
            return
        except ValueError:
            raise  # invalid voice/rate syntax: retrying will not help
        except Exception as exc:
            if attempt == attempts:
                raise TTSError(f"failed to synthesise {dst.name}: {exc!r}") from exc
            delay = min(60, 3 * attempt**2)
            log.warning(
                "%s: attempt %d failed (%r), retrying in %ds", dst.name, attempt, exc, delay
            )
            await asyncio.sleep(delay)


async def synthesize_all(
    jobs: Iterable[tuple[str, Path]],
    *,
    voice: str,
    rate: str = "+0%",
    parallel: int = 3,
    on_done: Callable[[str, Path], None] | None = None,
) -> None:
    """Synthesise many ``(text, destination)`` pairs with bounded concurrency."""
    semaphore = asyncio.Semaphore(max(1, parallel))

    async def run(text: str, dst: Path) -> None:
        async with semaphore:
            await synthesize(text, dst, voice=voice, rate=rate)
        if on_done is not None:
            on_done(text, dst)

    await asyncio.gather(*(run(text, dst) for text, dst in jobs))
