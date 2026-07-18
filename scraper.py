"""
Scrapers for Congreso de la República del Perú.
- Proyectos de ley: SPLEY API (api.congreso.gob.pe/spley-portal-service)
- Sesiones / Agenda / Destacados: DuckDuckGo news + fallback HTML
"""
import os
import httpx
import re
import urllib.parse
from bs4 import BeautifulSoup
from datetime import datetime

TIMEOUT = 25
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-PE,es;q=0.9",
    "Referer": "https://wb2server.congreso.gob.pe/spley-portal/",
}

SPLEY_API  = "https://api.congreso.gob.pe/spley-portal-service"
CONGRESO   = "https://www.congreso.gob.pe"
PER_PAR_ID = 2021   # periodo parlamentario actual 2021-2026


# ── Helpers ────────────────────────────────────────────────────

def _client():
    return httpx.AsyncClient(timeout=TIMEOUT, verify=False,
                             follow_redirects=True, headers=HEADERS)

def _fmt_date(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(str(s)[:25], fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass
    return str(s)[:10] if s else ""


async def _google_news(query: str, max_results: int = 15):
    """Fetch news from Google News RSS — results from Google's index."""
    import xml.etree.ElementTree as ET

    q = urllib.parse.quote(query)
    url = (
        f"https://news.google.com/rss/search"
        f"?q={q}&hl=es-419&gl=PE&ceid=PE:es"
    )
    try:
        async with _client() as c:
            r = await c.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; RSS reader)",
                "Accept": "application/rss+xml, application/xml",
            })
            if r.status_code != 200:
                return []
            root = ET.fromstring(r.text)
            items = root.findall(".//item")[:max_results]
            results = []
            for item in items:
                title  = item.findtext("title", "").strip()
                link   = item.findtext("link",  "").strip()
                source = item.findtext("source", "").strip()
                pubdate = item.findtext("pubDate", "")[:16]
                desc   = item.findtext("description", "")
                desc = re.sub(r'<[^>]+>', '', desc).strip()[:300]
                if title:
                    results.append({
                        "titulo":  title,
                        "fecha":   pubdate,
                        "fuente":  source,
                        "resumen": desc,
                        "enlace":  link,
                    })
            return results
    except Exception:
        return []


# ── Proyectos de ley ───────────────────────────────────────────

async def _fetch_spley_por_materia(materia: str, limit: int = 20):
    """
    SPLEY's strBusqueda does NOT filter by topic — it ignores the keyword and
    returns recent projects. For materia searches we fetch a large batch and
    filter client-side by keyword in the title.
    """
    keywords = [w.strip().upper() for w in materia.split() if len(w.strip()) > 2]
    if not keywords:
        return None

    # Fetch up to 300 recent projects and filter locally
    payload = {"perParId": PER_PAR_ID, "page": 0, "size": 300}
    try:
        async with _client() as c:
            r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro", json=payload)
            if r.status_code != 200:
                return None
            all_items = r.json().get("data", {}).get("proyectos", [])
    except Exception:
        return None

    matches = [
        p for p in all_items
        if any(kw in (p.get("titulo") or "").upper() for kw in keywords)
    ]

    if not matches:
        return {"sin_datos": True,
                "mensaje": f"No se encontraron proyectos sobre '{materia}' en el período actual."}

    return _format_proyectos(matches[:limit])


async def fetch_proyectos(autor=None, comision=None, numero=None, materia=None,
                          legislatura="2021-2026", limit=20):
    async with _client() as c:

        # Materia: SPLEY ignores strBusqueda for topic searches — use client-side filter
        if materia:
            result = await _fetch_spley_por_materia(materia, limit)
            if result is not None:
                return result

        # Build payload for SPLEY API
        payload: dict = {"perParId": PER_PAR_ID, "page": 0, "size": limit}

        if numero:
            payload["strBusqueda"] = numero.split("/")[0].strip()
        elif autor:
            payload["strBusqueda"] = autor
        elif comision:
            # Try to resolve commission name to ID
            try:
                rc = await c.get(f"{SPLEY_API}/comisiones")
                if rc.status_code == 200:
                    comisiones = rc.json().get("data", [])
                    match = next(
                        (x for x in comisiones
                         if comision.lower() in x.get("nombreComision", "").lower()),
                        None
                    )
                    if match:
                        payload["comisionId"] = match["comisionId"]
                    else:
                        payload["strBusqueda"] = comision
            except Exception:
                payload["strBusqueda"] = comision

        try:
            r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro",
                             json=payload)
            if r.status_code == 200:
                data = r.json().get("data", {})
                items = data.get("proyectos", [])
                if items:
                    return _format_proyectos(items[:limit])
        except Exception:
            pass

        return {
            "error": "No se pudo conectar con el sistema SPLEY del Congreso. "
                     "Consulta https://wb2server.congreso.gob.pe/spley-portal/"
        }


SPLEY_PORTAL = "https://wb2server.congreso.gob.pe/spley-portal/#/expediente"

def _format_proyectos(items):
    out = []
    for p in items:
        num = p.get("pleyNum") or ""
        out.append({
            "numero":              p.get("proyectoLey") or num or "",
            "fecha_presentacion":  _fmt_date(p.get("fecPresentacion") or ""),
            "estado":              p.get("desEstado") or "",
            "titulo":              p.get("titulo") or "",
            "sumilla":             p.get("sumilla") or p.get("titulo") or "",
            "proponente":          p.get("desProponente") or "",
            "autor":               p.get("autores") or p.get("desProponente") or "",
            "comision":            p.get("desComision") or "",
            "grupo_parlamentario": p.get("desGpar") or "",
            "legislatura":         p.get("desLegis") or "",
            "enlace":              f"{SPLEY_PORTAL}/{num}" if num else f"{SPLEY_PORTAL}/search",
        })
    return {"fuente": "SPLEY — api.congreso.gob.pe",
            "total": len(out), "items": out}


# ── Sesiones ───────────────────────────────────────────────────

async def fetch_sesiones(comision=None, fecha=None, limit=20):
    # Build a focused search query
    query = "sesiones comisiones congreso perú"
    if comision:
        query = f"sesión comisión {comision} congreso perú"
    if fecha:
        query += f" {fecha}"

    noticias = await _google_news(query, max_results=limit)

    if noticias:
        return {
            "fuente": "Noticias recientes del Congreso",
            "total": len(noticias),
            "items": noticias,
        }

    # Fallback: try comisiones2020 page HTML
    try:
        async with _client() as c:
            r = await c.get(f"{CONGRESO}/comisiones2020/")
            soup = BeautifulSoup(r.text, "html.parser")
            items = []
            for a in soup.select("a[href]")[:limit]:
                txt = a.get_text(strip=True)
                href = a.get("href", "")
                if len(txt) > 15:
                    items.append({"comision": txt, "enlace": href})
            if items:
                return {"fuente": "congreso.gob.pe/comisiones2020 (HTML)",
                        "total": len(items), "items": items}
    except Exception:
        pass

    return {
        "error": "No se pudo obtener información de sesiones. "
                 "Consulta https://wb2server.congreso.gob.pe/visor-sesiones/"
    }


# ── Agenda ─────────────────────────────────────────────────────

async def fetch_agenda():
    query = "agenda parlamentaria congreso perú sesiones pleno 2026"
    noticias = await _google_news(query, max_results=15)

    if noticias:
        return {
            "fuente": "Noticias recientes del Congreso",
            "total": len(noticias),
            "items": noticias,
        }

    # Fallback: scrape the agenda page HTML
    try:
        async with _client() as c:
            r = await c.get(f"{CONGRESO}/actas-agendas-y-acuerdos/"
                            "pleno-y-comision-permanente/agenda-del-pleno/")
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            lines = [l for l in text.split("\n") if len(l.strip()) > 20]
            if lines:
                return {"fuente": "congreso.gob.pe",
                        "contenido": "\n".join(lines[:60])}
    except Exception:
        pass

    return {
        "error": "No se pudo obtener la agenda parlamentaria. "
                 "Consulta https://www.congreso.gob.pe/actas-agendas-y-acuerdos/"
    }


# ── Destacados ─────────────────────────────────────────────────

async def fetch_destacados():
    """Scrapea congreso.gob.pe/home — secciones DESTACADO y CITACIONES con links de descarga."""
    try:
        async with _client() as c:
            r = await c.get(f"{CONGRESO}/home/", headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0",
            })
            if r.status_code != 200:
                raise Exception(f"HTTP {r.status_code}")

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")

        def _extract_items(widget_class):
            items = []
            widget = soup.find("div", class_=widget_class)
            if not widget:
                return items
            for a in widget.find_all("a", href=True):
                titulo = a.get_text(strip=True)
                enlace = a["href"].strip()
                if titulo and enlace:
                    items.append({"titulo": titulo, "enlace": enlace})
            return items

        destacados = _extract_items("widget_wc_widget_feature_article")
        citaciones  = _extract_items("widget_wc_widget_citation_article")

        if not destacados and not citaciones:
            raise Exception("sin items")

        return {
            "fuente": CONGRESO + "/home/",
            "destacados": destacados,
            "citaciones": citaciones,
        }

    except Exception:
        # Fallback: Google News RSS
        query = "congreso perú noticias destacados sesión pleno ley 2026"
        noticias = await _google_news(query, max_results=15)
        if noticias:
            return {"fuente": "Google News", "items": noticias}
        return {"error": "No se pudo obtener las noticias del Congreso."}


# ── Congresista ────────────────────────────────────────────────

async def fetch_congresista(nombre: str):
    """Proyectos presentados + noticias recientes de un congresista."""
    import asyncio

    # Proyectos en SPLEY
    proyectos_task = fetch_proyectos(autor=nombre, limit=30)
    # Noticias en Google News
    noticias_task  = _google_news(f"{nombre} congresista peru", max_results=10)

    proyectos, noticias = await asyncio.gather(proyectos_task, noticias_task)

    # Agrupar proyectos por estado
    resumen_estados: dict = {}
    if "items" in proyectos:
        for p in proyectos["items"]:
            estado = p.get("estado") or "Sin estado"
            resumen_estados[estado] = resumen_estados.get(estado, 0) + 1

    return {
        "congresista": nombre,
        "proyectos": proyectos,
        "resumen_estados": resumen_estados,
        "noticias_recientes": noticias,
        "perfil_url": f"https://wb2server.congreso.gob.pe/spley-portal/#/busqueda?autor={urllib.parse.quote(nombre)}",
    }


# ── Rastrear proyecto específico ───────────────────────────────

async def fetch_estado_proyecto(numero: str):
    """Estado detallado de un proyecto de ley por número."""
    # Extract just the numeric part for search (e.g. "14860/2025-CR" → "14860")
    num_clean = numero.split("/")[0].strip()
    async with _client() as c:
        payload = {
            "perParId":    PER_PAR_ID,
            "strBusqueda": num_clean,
            "page":        0,
            "size":        10,
        }
        try:
            r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro", json=payload)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("proyectos", [])
                # Find exact match first, then fall back to first result
                exact = next(
                    (p for p in items if num_clean in (p.get("proyectoLey") or p.get("pleyNum") or "")),
                    items[0] if items else None
                )
                if exact:
                    p   = exact
                    num = p.get("pleyNum") or ""
                    return {
                        "numero":        p.get("proyectoLey") or num,
                        "titulo":        p.get("titulo") or "",
                        "estado":        p.get("desEstado") or "",
                        "fecha_ingreso": _fmt_date(p.get("fecPresentacion") or ""),
                        "autor":         p.get("autores") or p.get("desProponente") or "",
                        "comision":      p.get("desComision") or "",
                        "sumilla":       p.get("sumilla") or p.get("titulo") or "",
                        "enlace":        f"{SPLEY_PORTAL}/{num}" if num else "",
                        "fuente":        "SPLEY — api.congreso.gob.pe",
                    }
        except Exception:
            pass

    return {"error": f"No se encontró el proyecto '{numero}'. Verifica el número e intenta de nuevo."}


# ── Videos YouTube del Congreso ────────────────────────────────

YT_CHANNEL = "https://www.youtube.com/@congresodelarepublicaperu/streams"

async def fetch_videos_youtube(limit=20):
    """Lista los videos más recientes del canal oficial del Congreso."""
    import asyncio, yt_dlp

    def _extract():
        opts = {
            "quiet":        True,
            "no_warnings":  True,
            "extract_flat": True,
            "playlist_items": f"1-{limit}",
            **_ydl_cookie_opts(),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(YT_CHANNEL, download=False)
            entries = info.get("entries") or []
            videos = []
            for e in entries:
                vid_id      = e.get("id") or ""
                title       = e.get("title") or ""
                duration    = e.get("duration")
                timestamp   = e.get("timestamp") or e.get("release_timestamp")
                live_status = e.get("live_status") or "not_live"
                is_live     = live_status in ("is_live", "is_upcoming")
                was_live    = live_status in ("was_live", "post_live")
                fecha = ""
                if timestamp:
                    fecha = datetime.utcfromtimestamp(timestamp).strftime("%d/%m/%Y")
                dur_str = ""
                try:
                    if duration:
                        total_s = int(duration)
                        h, rem = divmod(total_s, 3600)
                        m, s   = divmod(rem, 60)
                        dur_str = f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
                except (TypeError, ValueError):
                    pass
                videos.append({
                    "id":        vid_id,
                    "titulo":    title,
                    "fecha":     fecha,
                    "duracion":  dur_str,
                    "en_vivo":   is_live,
                    "fue_live":  was_live,
                    "url":       f"https://www.youtube.com/watch?v={vid_id}" if vid_id else "",
                    "thumb":     f"https://img.youtube.com/vi/{vid_id}/mqdefault.jpg" if vid_id else "",
                })
            return videos

    loop = asyncio.get_event_loop()
    try:
        videos = await loop.run_in_executor(None, _extract)
        return {"ok": True, "videos": videos}
    except Exception as e:
        return {"ok": False, "error": str(e)}


import sys

COOKIE_PATHS = [
    os.path.expanduser("~/youtube.cookies"),
    os.path.expanduser("~/youtube_cookies.txt"),
    os.path.expanduser("~/Downloads/youtube.cookies"),
]

# On macOS, yt-dlp can read browser cookies directly from the OS keychain
_MAC_BROWSERS = ["chrome", "safari", "firefox", "chromium"]
_cookie_opts_cache = None


def _get_cookie_path():
    for p in COOKIE_PATHS:
        if os.path.exists(p):
            return p
    return None


def _ydl_cookie_opts():
    """Returns cookie options for yt-dlp. Cached after first call."""
    global _cookie_opts_cache
    if _cookie_opts_cache is not None:
        return _cookie_opts_cache

    # Cookie file always wins
    path = _get_cookie_path()
    if path:
        _cookie_opts_cache = {"cookiefile": path}
        return _cookie_opts_cache

    # On macOS, probe which browser is available and cache it
    if sys.platform == "darwin":
        import yt_dlp
        for browser in _MAC_BROWSERS:
            try:
                from yt_dlp.cookies import extract_cookies_from_browser

                class _SilentLogger:
                    def debug(self, *a): pass
                    def warning(self, *a): pass
                    def error(self, *a): pass

                jar = extract_cookies_from_browser(browser, None, _SilentLogger())
                if jar is not None:
                    _cookie_opts_cache = {"cookiesfrombrowser": (browser,)}
                    return _cookie_opts_cache
            except Exception:
                continue

    _cookie_opts_cache = {}
    return _cookie_opts_cache


def _parse_vtt(content: str) -> str:
    """Extract plain text from a VTT subtitle file."""
    lines, seen = [], set()
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line:
            continue
        # Remove HTML tags and timestamps
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean and clean not in seen:
            seen.add(clean)
            lines.append(clean)
    return " ".join(lines)


def _resolve_yt_info(video_id: str) -> dict:
    """Extract video info (URL, subtitles) without downloading anything."""
    import yt_dlp
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "bestaudio[protocol=m3u8_native]/bestaudio[protocol=m3u8]/bestaudio/best",
        **_ydl_cookie_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def get_yt_captions(video_id: str):
    """
    Obtiene subtítulos de YouTube via extract_info (no descarga archivos).
    Retorna dict con ok/text/source, o None si no hay subtítulos.
    """
    import httpx

    try:
        info = _resolve_yt_info(video_id)
    except Exception:
        return None

    # Buscar en subtítulos manuales primero, luego automáticos
    for sub_dict in [info.get("subtitles", {}), info.get("automatic_captions", {})]:
        for lang in ["es", "es-419", "es-US", "es-MX"]:
            tracks = sub_dict.get(lang, [])
            # Preferir vtt, luego cualquier formato
            vtt_url = next((t["url"] for t in tracks if t.get("ext") == "vtt"), None)
            if not vtt_url and tracks:
                vtt_url = tracks[0].get("url")
            if not vtt_url:
                continue
            try:
                resp = httpx.get(vtt_url, timeout=20, follow_redirects=True)
                text = _parse_vtt(resp.text)
                if text.strip():
                    return {"ok": True, "text": text[:40000], "source": "subtitulos"}
            except Exception:
                continue

    return None


def transcribe_with_whisper(video_id: str, api_key: str, minutes: int = 10):
    """
    Captura hasta `minutes` minutos de audio via ffmpeg+HLS y transcribe con Groq Whisper.
    Usa el mismo enfoque que el live transcriber: resolve URL con yt-dlp, captura con ffmpeg.
    """
    import tempfile
    import subprocess
    from groq import Groq

    seconds = minutes * 60

    # Resolver URL de audio sin descargar
    try:
        info = _resolve_yt_info(video_id)
    except Exception as e:
        err = str(e)
        return {"ok": False, "error": f"No se pudo obtener el video de YouTube: {err[:200]}"}

    fmts = info.get("requested_formats") or [info]
    stream_url = fmts[0].get("url") or info.get("url", "")
    if not stream_url:
        return {"ok": False, "error": "No se pudo resolver la URL del audio."}

    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "audio.wav")
        cmd = [
            "ffmpeg", "-y",
            "-i", stream_url,
            "-vn",
            "-ar", "16000",
            "-ac", "1",
            "-t", str(seconds),
            out_path,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=seconds + 60)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Tiempo de espera agotado al capturar el audio."}
        except FileNotFoundError:
            return {"ok": False, "error": "ffmpeg no está instalado. Instálalo con: sudo apt install ffmpeg"}

        if not os.path.exists(out_path) or os.path.getsize(out_path) < 4096:
            stderr = result.stderr.decode(errors="ignore")[-300:]
            return {"ok": False, "error": f"No se pudo capturar el audio del video. {stderr}"}

        size_mb = os.path.getsize(out_path) / 1_000_000
        client = Groq(api_key=api_key)
        with open(out_path, "rb") as f:
            tr = client.audio.transcriptions.create(
                file=(os.path.basename(out_path), f.read()),
                model="whisper-large-v3-turbo",
                language="es",
                response_format="text",
            )
        text = tr if isinstance(tr, str) else tr.text
        return {
            "ok": True,
            "text": text[:40000],
            "source": "whisper",
            "nota": f"Transcripción de los primeros {minutes} min ({size_mb:.1f} MB de audio)",
        }


async def fetch_transcript_youtube(video_id: str, api_key: str = ""):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_yt_captions, video_id)


# ── AES encryption for SPLEY expediente API ───────────────────

_SPLEY_KEY = "ProdALg5ZrAsxBMD"

def _spley_encrypt(value: str) -> str:
    import base64
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad
    key = _SPLEY_KEY.encode("utf-8")
    cipher = AES.new(key, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(value.encode("utf-8"), AES.block_size))
    b64 = base64.b64encode(encrypted).decode("utf-8")
    return b64.replace("+", "-").replace("/", "_").replace("=", "")


# ── Expediente completo de un proyecto ────────────────────────

async def fetch_expediente(numero: str):
    """
    Obtiene el expediente completo de un proyecto: comisiones asignadas,
    seguimiento cronológico de actos, predictamen/dictamen y grupo parlamentario.
    """
    num_clean = numero.split("/")[0].strip()

    # Resolve pleyNum from list if needed
    async with _client() as c:
        r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro",
                         json={"perParId": PER_PAR_ID, "strBusqueda": num_clean,
                               "page": 0, "size": 10})
        if r.status_code != 200:
            return {"error": f"No se pudo buscar el proyecto {numero}."}
        items = r.json().get("data", {}).get("proyectos", [])
        exact = next(
            (p for p in items if num_clean in (p.get("proyectoLey") or p.get("pleyNum",""))),
            items[0] if items else None,
        )
        if not exact:
            return {"error": f"Proyecto {numero} no encontrado."}
        pley_num = str(exact["pleyNum"])

    enc_per = _spley_encrypt(str(PER_PAR_ID))
    enc_ple = _spley_encrypt(pley_num)
    import asyncio as _asyncio

    base_url = f"{SPLEY_API}/expediente/{enc_per}/{enc_ple}"

    async def _get(c, path):
        try:
            r = await c.get(f"{base_url}{path}")
            if r.status_code == 200:
                return r.json().get("data", {})
        except Exception:
            pass
        return {}

    async with _client() as c:
        results = await _asyncio.gather(
            _get(c, ""),
            _get(c, "/acumulados"),
            _get(c, "/secciones"),
            _get(c, "/opinion-ciudadana"),
            return_exceptions=True,
        )

    data            = results[0] if isinstance(results[0], dict) else {}
    data_acumulados = results[1] if isinstance(results[1], dict) else {}
    data_secciones  = results[2] if isinstance(results[2], dict) else {}
    data_opinion    = results[3] if isinstance(results[3], dict) else {}

    if not data:
        return {"error": f"No se pudo obtener el expediente del proyecto {numero}."}

    general      = data.get("general", {})
    comisiones   = data.get("comisiones", [])
    seguimientos = data.get("seguimientos", [])

    ARCHIVO_BASE = "https://api.congreso.gob.pe/spley-portal-service/expediente/archivo"

    def _archivo_url(a):
        ruta = a.get("rutaArchivo") or a.get("ruta") or ""
        nombre = a.get("nombreArchivo") or ""
        if ruta and ruta.startswith("http"):
            return ruta
        if ruta:
            return f"{ARCHIVO_BASE}/{ruta}"
        if nombre:
            return f"{ARCHIVO_BASE}/{nombre}"
        return ""

    def _fmt_archivo(a):
        return {
            "nombre":      a.get("nombreArchivo") or "",
            "descripcion": a.get("descripcion") or a.get("desArchivo") or a.get("nombreArchivo") or "",
            "url":         _archivo_url(a),
            "tipo":        a.get("tipoArchivo") or "pdf",
        }

    # Format seguimientos (chronological acts)
    actos = []
    todos_archivos = []
    for s in reversed(seguimientos):
        archivos_acto = [_fmt_archivo(a) for a in s.get("archivos", []) if a.get("activo") or a.get("nombreArchivo")]
        todos_archivos.extend(archivos_acto)
        actos.append({
            "fecha":     s.get("fecha", "")[:10],
            "estado":    s.get("desEstado", ""),
            "comision":  s.get("desComisiones") or "",
            "detalle":   (s.get("detalle") or "")[:300],
            "adjuntos":  archivos_acto,
        })

    # Detect predictamen / dictamen
    dictamen = next(
        (a for s in seguimientos for a in s.get("archivos", [])
         if "dictamen" in (a.get("descripcion") or "").lower()
         or "dictamen" in (a.get("nombreArchivo") or "").lower()),
        None,
    )

    # Proyectos acumulados
    pley_acumulados = []
    for p in (data_acumulados if isinstance(data_acumulados, list) else data_acumulados.get("proyectos", [])):
        pley_acumulados.append({
            "numero":  p.get("proyectoLey") or p.get("pleyNum") or "",
            "titulo":  p.get("titulo") or "",
            "estado":  p.get("desEstado") or "",
            "enlace":  f"{SPLEY_PORTAL}/{p.get('pleyNum','')}" if p.get("pleyNum") else "",
        })

    # Secciones (texto articulado del proyecto)
    secciones = []
    for s in (data_secciones if isinstance(data_secciones, list) else data_secciones.get("secciones", [])):
        secciones.append({
            "titulo":  s.get("titulo") or s.get("nombre") or "",
            "texto":   (s.get("texto") or s.get("contenido") or "")[:3000],
        })

    # Opinión ciudadana
    opinion = {}
    if isinstance(data_opinion, dict):
        opinion = {
            "total_opiniones": data_opinion.get("total") or data_opinion.get("totalOpiniones") or 0,
            "a_favor":         data_opinion.get("aFavor") or data_opinion.get("favor") or 0,
            "en_contra":       data_opinion.get("enContra") or data_opinion.get("contra") or 0,
            "comentarios":     len(data_opinion.get("comentarios") or data_opinion.get("opiniones") or []),
        }

    return {
        "numero":                general.get("proyectoLey", numero),
        "titulo":                general.get("titulo", ""),
        "sumilla":               general.get("sumilla") or general.get("titulo", ""),
        "estado":                general.get("desEstado", ""),
        "fecha_presentacion":    _fmt_date(general.get("fecPresentacion") or ""),
        "periodo_parlamentario": general.get("desPerPar") or "2021-2026",
        "legislatura":           general.get("desLegis", ""),
        "proponente":            general.get("desProponente", ""),
        "autor_principal":       general.get("autores") or general.get("desProponente") or "",
        "coautores":             general.get("coAutores") or general.get("coautores") or "",
        "adherentes":            general.get("adherentes") or "",
        "grupo_parlamentario":   general.get("desGpar", ""),
        "comisiones":            [
            {
                "nombre": c.get("nombre") or c.get("desComision") or "",
                "id":     c.get("comisionId") or c.get("id") or "",
                "enlace": (
                    f"https://www2.congreso.gob.pe/Sicr/ApoyComisiones/comision2011.nsf/"
                    f"ComisionesVirtual?OpenForm&comision={c.get('comisionId','')}"
                    if c.get("comisionId") else ""
                ),
            }
            for c in comisiones
        ],
        "fases":                 [f["fase"] for f in data.get("fases", []) if f.get("tipo") in (1, 2)],
        "actos":                 actos,
        "todos_los_adjuntos":    todos_archivos,
        "proyectos_acumulados":  pley_acumulados,
        "secciones":             secciones,
        "opinion_ciudadana":     opinion,
        "predictamen":           {
            "fecha":   dictamen.get("fecha", "")[:10] if dictamen else None,
            "nombre":  dictamen.get("nombreArchivo") if dictamen else None,
            "url":     _archivo_url(dictamen) if dictamen else None,
        } if dictamen else None,
        "enlace_expediente":     f"{SPLEY_PORTAL}/{general.get('pleyNum', '')}",
        "fuente":                f"SPLEY expediente — {SPLEY_API}",
    }


# ── Agenda de comisiones (próximos días) ──────────────────────

SINTESIS_URL = (
    "https://www2.congreso.gob.pe/Sicr/ApoyComisiones/comision2011.nsf/"
    "new_04pa_sintagenNS?OpenForm&Start=1&Count=1000&ExpandView"
)
CONGRESO2 = "https://www2.congreso.gob.pe"


async def fetch_agenda_comisiones(dias: int = 2, comision: str = None):
    """
    Obtiene la agenda de sesiones de comisiones para los próximos días desde
    las Síntesis de Agendas del Departamento de Comisiones (sistema Lotus Notes,
    la misma fuente que muestra el iframe de congreso.gob.pe/agendas-del-dia).
    Cada síntesis detalla comisión, sesión, hora, lugar y plataforma.
    `comision` filtra opcionalmente por nombre (o parte del nombre).
    """
    from datetime import timedelta

    today = datetime.now().date()
    limite = today + timedelta(days=max(dias, 1))

    async with _client() as c:
        r = await c.get(SINTESIS_URL)
        if r.status_code != 200:
            return {"error": "No se pudo obtener la lista de síntesis de agendas."}
        soup = BeautifulSoup(r.text, "html.parser")

        # Entradas con formato "dd/mm/yyyy, Síntesis de Agendas"
        entradas = []
        for a in soup.select("a[href]"):
            text = a.get_text(strip=True)
            m = re.match(r"(\d{2}/\d{2}/\d{4})", text)
            if m and "OpenDocument" in a.get("href", ""):
                try:
                    fecha = datetime.strptime(m.group(1), "%d/%m/%Y").date()
                except ValueError:
                    continue
                href = a["href"]
                enlace = href if href.startswith("http") else CONGRESO2 + href
                entradas.append({"fecha": fecha, "enlace": enlace})

        # Solo síntesis dentro del rango [hoy, hoy+dias] — sin fallback a datos viejos
        en_rango = [e for e in entradas if today <= e["fecha"] <= limite]
        vigentes = en_rango
        nota = None

        sintesis = []
        for e in vigentes[:3]:
            try:
                rd = await c.get(e["enlace"])
                if rd.status_code != 200:
                    continue
                dsoup = BeautifulSoup(rd.text, "html.parser")
                texto = dsoup.get_text(separator="\n", strip=True)
                lineas = [l for l in texto.split("\n") if len(l.strip()) > 2]
                contenido = "\n".join(lineas)[:4000]
                if comision and comision.lower() not in contenido.lower():
                    continue
                sintesis.append({
                    "fecha_sintesis": e["fecha"].strftime("%d/%m/%Y"),
                    "enlace": e["enlace"],
                    "contenido": contenido,
                })
            except Exception:
                continue

    if not sintesis:
        return {"sin_datos": True,
                "mensaje": "No se encontraron sesiones de comisiones programadas"
                           + (f" para '{comision}'" if comision else "")
                           + " en los próximos días."}

    return {
        "fuente": "Síntesis de Agendas — Departamento de Comisiones, congreso.gob.pe",
        "dias_consultados": dias,
        "nota": nota,
        "sintesis": sintesis,
        "instruccion": ("Cada síntesis lista las sesiones agrupadas por día: "
                        "comisión, tipo de sesión, hora, edificio/sala y plataforma. "
                        "Extrae SOLO las sesiones de los días consultados."),
    }


# ── Agenda del Pleno ──────────────────────────────────────────

AGENDA_PLENO_URL = (
    "https://www2.congreso.gob.pe/Sicr/RelatAgenda/PlenoComiPerm20112016.nsf/"
    "new_agendapleno?OpenForm&Start=1&Count=1000&ExpandView"
)


async def fetch_agenda_pleno():
    """
    Obtiene la Agenda del Pleno más reciente desde el sistema de Relatoría
    (la misma fuente del iframe de congreso.gob.pe/agenda-del-pleno).
    El documento es un PDF: se extrae el texto con PyMuPDF y se cuentan
    los tipos de asuntos agendados.
    """
    async with _client() as c:
        r = await c.get(AGENDA_PLENO_URL)
        if r.status_code != 200:
            return {"error": "No se pudo obtener la lista de agendas del Pleno."}
        soup = BeautifulSoup(r.text, "html.parser")

        docs = [(a.get_text(strip=True), a["href"]) for a in soup.select("a[href]")
                if "/Apleno/" in a.get("href", "") and a.get_text(strip=True)]
        if not docs:
            return {"error": "No se encontraron agendas del Pleno publicadas."}

        titulo, enlace = docs[0]  # la más reciente
        rd = await c.get(enlace)
        if rd.status_code != 200:
            return {"error": "No se pudo descargar la agenda del Pleno."}

    # El documento es un PDF servido directamente
    try:
        import fitz
        doc = fitz.open(stream=rd.content, filetype="pdf")
        texto = "\n".join(page.get_text() for page in doc).strip()
    except Exception:
        texto = BeautifulSoup(rd.text, "html.parser").get_text(separator="\n", strip=True)

    low = texto.lower()
    conteo = {
        "dictámenes":                 low.count("dictamen"),
        "denuncias_constitucionales": low.count("denuncia constitucional"),
        "mociones":                   low.count("moción") + low.count("mocion"),
        "insistencias":               low.count("insistencia"),
        "interpelaciones":            low.count("interpelac"),
        "proyectos_ley":              low.count("proyecto de ley"),
    }

    return {
        "fuente": "Relatoría del Congreso — Agenda del Pleno",
        "titulo": titulo,
        "enlace": enlace,
        "conteo_aproximado": conteo,
        "nota": ("El conteo es aproximado (menciones en el texto). "
                 "Usa el texto para el detalle de cada asunto agendado."),
        "texto": texto[:8000],
        "agendas_anteriores": [
            {"titulo": t, "enlace": h} for t, h in docs[1:4]
        ],
    }


# ── Mociones de interpelación ─────────────────────────────────

async def fetch_interpelaciones(ministro: str = None):
    """
    Busca mociones de interpelación presentadas en el Congreso.
    1) Busca en SPLEY por keyword "interpelacion" para obtener mociones formales.
    2) Complementa con Google News para las que están juntando firmas.
    """
    import asyncio

    kw_filter = (ministro or "").upper()

    # ── 1. Buscar mociones formales en SPLEY ──────────────────────
    mociones_spley = []
    try:
        payload = {"perParId": PER_PAR_ID, "page": 0, "size": 300}
        async with _client() as c:
            r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro", json=payload)
            if r.status_code == 200:
                all_items = r.json().get("data", {}).get("proyectos", [])
                for p in all_items:
                    titulo = (p.get("titulo") or "").upper()
                    sumilla = (p.get("sumilla") or "").upper()
                    if "INTERPELAC" in titulo or "INTERPELAC" in sumilla or "MOCIÓN" in titulo:
                        if not kw_filter or kw_filter in titulo or kw_filter in sumilla:
                            num = p.get("pleyNum") or ""
                            mociones_spley.append({
                                "numero":    p.get("proyectoLey") or num or "",
                                "titulo":    p.get("titulo") or "",
                                "estado":    p.get("desEstado") or "",
                                "fecha":     _fmt_date(p.get("fecPresentacion") or ""),
                                "proponente": p.get("desProponente") or p.get("autores") or "",
                                "comision":  p.get("desComision") or "",
                                "enlace":    f"{SPLEY_PORTAL}/{num}" if num else "",
                            })
    except Exception:
        pass

    # ── 2. Noticias recientes (prensa) ────────────────────────────
    base = f"interpelación {ministro} " if ministro else "interpelación ministro "
    queries = [
        f"moción {base}congreso peru 2026",
        f"{base}congreso peru firmas",
    ]
    news_tasks = [_google_news(q, max_results=6) for q in queries]
    news_results = await asyncio.gather(*news_tasks)

    seen_news, noticias = set(), []
    for lista in news_results:
        for n in lista:
            if n["enlace"] not in seen_news:
                seen_news.add(n["enlace"])
                noticias.append(n)

    if not mociones_spley and not noticias:
        return {
            "sin_datos": True,
            "mensaje": "No se encontraron mociones de interpelación activas en este momento.",
        }

    return {
        "fuente": "SPLEY (mociones formales) + Google News (prensa)",
        "mociones_formales": mociones_spley,
        "total_formales": len(mociones_spley),
        "noticias_prensa": noticias,
    }
