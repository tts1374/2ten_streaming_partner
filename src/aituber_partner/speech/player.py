"""Local WAV playback for generated speech audio."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


class WaveAudioPlayer:
    """Play generated WAV files on the local machine."""

    async def play(self, audio_path: str) -> None:
        await asyncio.to_thread(self._play_sync, audio_path)

    def _play_sync(self, audio_path: str) -> None:
        path = Path(audio_path)
        if not path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        if sys.platform != "win32":
            raise RuntimeError("WAV playback is only implemented for Windows in Phase 1")

        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
