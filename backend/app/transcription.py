import logging
import os
from base64 import b64encode
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

DEFAULT_TRANSCRIBE_PROMPT = "transcribe this voice message, return only message content"


def _format_to_mime(audio_format: str) -> str:
    mapping = {
        "wav": "audio/wav",
        "mp3": "audio/mpeg",
        "flac": "audio/flac",
        "m4a": "audio/mp4",
        "ogg": "audio/ogg",
    }
    return mapping[audio_format]


def _detect_audio_format(audio_file: Any, filename: str) -> Optional[str]:
    if isinstance(audio_file, (bytes, bytearray)):
        header = bytes(audio_file[:32])
        if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return "wav"
        if header.startswith(b"fLaC"):
            return "flac"
        if header.startswith(b"OggS"):
            return "ogg"
        if header.startswith(b"ID3") or (
            len(header) > 1 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0
        ):
            return "mp3"
        if b"ftyp" in header:
            return "m4a"
        if header.startswith(b"\x1A\x45\xDF\xA3"):
            return None

    extension = Path(filename).suffix.lower().lstrip(".")
    if extension in {"mp3", "wav", "flac", "m4a", "ogg"}:
        return extension
    if extension in {"mpeg", "mpga"}:
        return "mp3"
    if extension == "mp4":
        return "m4a"
    return None


@lru_cache(maxsize=1)
def _get_transcribe_llm() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_BASE_URL are required")

    model = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=0,
    )


def transcribe_audio(audio_file: Any, filename: str, prompt: Optional[str] = None) -> str:
    llm = _get_transcribe_llm()

    audio_format = _detect_audio_format(audio_file, filename)
    raw_size = len(audio_file) if isinstance(audio_file, (bytes, bytearray)) else None
    header_hex = bytes(audio_file[:16]).hex() if isinstance(audio_file, (bytes, bytearray)) else "n/a"
    logger.info(
        "[audio][llm] detected format=%s filename=%s model=%s size=%s header_hex=%s",
        audio_format,
        filename,
        os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe"),
        raw_size,
        header_hex,
    )

    if audio_format is None:
        raise RuntimeError("Unsupported audio format. Use mp3, flac, m4a, wav, or ogg.")

    message_prompt = (prompt or DEFAULT_TRANSCRIBE_PROMPT).strip()
    encoded_audio = b64encode(audio_file).decode("ascii")
    mime_type = _format_to_mime(audio_format)

    response = llm.invoke(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": message_prompt},
                    {
                        "type": "audio",
                        "mime_type": mime_type,
                        "base64": encoded_audio,
                    },
                ],
            }
        ]
    )

    text = (response.text or "").strip()
    logger.info("[audio][llm] response received text_len=%s", len(text))
    return text
