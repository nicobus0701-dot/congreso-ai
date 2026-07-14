"""
Pipeline de transcripción en vivo para streams de YouTube.
Extrae audio en chunks de 10s con ffmpeg y transcribe con Groq Whisper.
"""
import asyncio
import os
import time
import json
import subprocess
import tempfile
from pathlib import Path

# NOTE: Using YouTube streams via yt-dlp + ffmpeg may conflict with YouTube ToS
# in a public production context. Fine for personal/dev use.


def get_stream_url(video_id: str) -> tuple:
    """
    Returns (stream_url, is_live).
    Uses yt-dlp to resolve the best audio HLS URL.
    """
    import yt_dlp
    from scraper import _ydl_cookie_opts

    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio[protocol=m3u8_native]/bestaudio[protocol=m3u8]/bestaudio/best",
        **_ydl_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    is_live = bool(info.get("is_live") or info.get("was_live"))

    # Prefer the resolved URL from the selected format
    fmts = info.get("requested_formats") or [info]
    stream_url = fmts[0].get("url") or info.get("url", "")
    if not stream_url:
        raise ValueError("No se pudo resolver la URL del stream de YouTube.")
    return stream_url, is_live


def _transcribe_wav(path: str, api_key: str) -> str:
    """Transcribe a .wav file with Groq Whisper. Returns text or empty string."""
    from groq import Groq

    size = os.path.getsize(path)
    if size < 4096:  # skip near-empty chunks
        return ""

    client = Groq(api_key=api_key)
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model="whisper-large-v3-turbo",
            language="es",
            response_format="text",
        )
    text = result if isinstance(result, str) else getattr(result, "text", "")
    return text.strip()


async def stream_transcription(video_id: str, api_key: str):
    """
    Async generator that yields dicts as each audio chunk is transcribed.
    Yields:
      {"status": "..."} — status updates
      {"timestamp": "mm:ss", "text": "...", "elapsed": int} — transcription lines
      {"error": "..."} — on failure
    """
    loop = asyncio.get_event_loop()

    # ── Step 1: resolve stream URL ──────────────────────────────
    yield {"status": "Resolviendo URL del stream..."}
    try:
        stream_url, is_live = await loop.run_in_executor(None, get_stream_url, video_id)
    except Exception as e:
        yield {"error": f"No se pudo obtener el stream: {e}"}
        return

    kind = "live" if is_live else "video"
    yield {"status": f"Stream resuelto ({kind}). Iniciando captura de audio..."}

    # ── Step 2: ffmpeg segments in a temp dir ───────────────────
    with tempfile.TemporaryDirectory() as tmp:
        chunk_pat = os.path.join(tmp, "chunk%04d.wav")

        cmd = [
            "ffmpeg", "-y",
            "-i", stream_url,
            "-vn",                   # audio only
            "-ar", "16000",          # 16 kHz — Whisper optimal
            "-ac", "1",              # mono
            "-f", "segment",
            "-segment_time", "10",   # 10-second chunks
            "-reset_timestamps", "1",
            chunk_pat,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        yield {"status": "Capturando audio... (primera transcripción en ~10 s)"}

        processed: set = set()
        start_real = time.time()

        try:
            while True:
                # Check if ffmpeg died
                if proc.returncode is not None and proc.returncode != 0:
                    stderr_out = b""
                    try:
                        stderr_out = await asyncio.wait_for(proc.stderr.read(), timeout=2)
                    except Exception:
                        pass
                    yield {"error": f"ffmpeg terminó inesperadamente (código {proc.returncode}). {stderr_out.decode()[:200]}"}
                    return

                # Scan for completed .wav chunks (skip the last — still being written)
                wav_files = sorted(Path(tmp).glob("chunk*.wav"))
                completed = wav_files[:-1] if len(wav_files) > 1 else []

                for wav in completed:
                    name = wav.name
                    if name in processed:
                        continue
                    processed.add(name)

                    # Chunk index → elapsed time offset
                    chunk_idx = int(wav.stem.replace("chunk", ""))
                    elapsed = chunk_idx * 10
                    ts = f"{elapsed // 60:02d}:{elapsed % 60:02d}"

                    try:
                        text = await loop.run_in_executor(None, _transcribe_wav, str(wav), api_key)
                    except Exception as exc:
                        yield {"error": f"Error al transcribir chunk {name}: {exc}"}
                        continue

                    if text:
                        yield {"timestamp": ts, "text": text, "elapsed": elapsed}

                    # Clean up to save disk space
                    try:
                        wav.unlink()
                    except Exception:
                        pass

                await asyncio.sleep(2)

        except asyncio.CancelledError:
            pass
        finally:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    proc.kill()
