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
            "numero":   p.get("proyectoLey") or num or "",
            "fecha":    _fmt_date(p.get("fecPresentacion") or ""),
            "estado":   p.get("desEstado") or "",
            "sumilla":  (p.get("titulo") or "")[:140],
            "autor":    (p.get("autores") or p.get("desProponente") or "")[:120],
            "enlace":   f"{SPLEY_PORTAL}/{num}" if num else f"{SPLEY_PORTAL}/search",
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
                if duration:
                    h, m = divmod(int(duration) // 60, 60)
                    s    = int(duration) % 60
                    dur_str = f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"
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


def get_yt_captions(video_id: str):
    """
    Obtiene subtítulos de YouTube usando yt-dlp.
    En macOS usa las cookies del browser instalado automáticamente.
    Retorna dict con ok/text/source, o None si no hay subtítulos disponibles.
    """
    import tempfile
    import yt_dlp

    url = f"https://www.youtube.com/watch?v={video_id}"

    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "quiet":           True,
            "no_warnings":     True,
            "skip_download":   True,
            "writeautomaticsub": True,
            "writesubtitles":  True,
            "subtitleslangs":  ["es", "es-419"],
            "subtitlesformat": "vtt",
            "outtmpl":         os.path.join(tmp, "subs"),
            **_ydl_cookie_opts(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception:
            return None

        vtt_files = [f for f in os.listdir(tmp) if f.endswith(".vtt")]
        if not vtt_files:
            return None

        content = open(os.path.join(tmp, vtt_files[0]), encoding="utf-8").read()
        text = _parse_vtt(content)
        if text.strip():
            return {"ok": True, "text": text[:40000], "source": "subtitulos"}
    return None


def transcribe_with_whisper(video_id: str, api_key: str, minutes: int = 10):
    """
    Descarga hasta `minutes` minutos de audio y transcribe con Groq Whisper.
    Usa el bitrate más bajo posible para minimizar el tiempo de descarga.
    """
    import tempfile
    import yt_dlp
    from groq import Groq

    url     = f"https://www.youtube.com/watch?v={video_id}"
    seconds = minutes * 60

    with tempfile.TemporaryDirectory() as tmp:
        opts = {
            "quiet":       True,
            "no_warnings": True,
            "format": "worstaudio/bestaudio/best",
            "outtmpl": os.path.join(tmp, "audio.%(ext)s"),
            "postprocessors": [{"key": "FFmpegExtractAudio",
                                "preferredcodec": "mp3",
                                "preferredquality": "32"}],
            "download_ranges":        yt_dlp.utils.download_range_func(None, [(0, seconds)]),
            "force_keyframes_at_cuts": True,
            **_ydl_cookie_opts(),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as e:
            err = str(e)
            if "Sign in" in err or "bot" in err.lower():
                return {"ok": False, "error": "YouTube bloquea la descarga de este stream en vivo. El resumen estará disponible cuando termine la transmisión y se generen los subtítulos automáticos."}
            return {"ok": False, "error": f"No se pudo descargar el audio: {err[:200]}"}

        mp3 = next((os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".mp3")), None)
        if not mp3:
            return {"ok": False, "error": "No se pudo descargar el audio del video."}

        size_mb = os.path.getsize(mp3) / 1_000_000
        client  = Groq(api_key=api_key)
        with open(mp3, "rb") as f:
            result = client.audio.transcriptions.create(
                file=(os.path.basename(mp3), f.read()),
                model="whisper-large-v3-turbo",
                language="es",
                response_format="text",
            )
        text = result if isinstance(result, str) else result.text
        return {
            "ok":    True,
            "text":  text[:40000],
            "source": "whisper",
            "nota":  f"Transcripción de los primeros {minutes} min ({size_mb:.1f} MB de audio)",
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
    url = f"{SPLEY_API}/expediente/{enc_per}/{enc_ple}"
    async with _client() as c:
        r = await c.get(url)
        if r.status_code != 200:
            return {"error": f"No se pudo obtener el expediente del proyecto {numero}."}
        data = r.json().get("data", {})

    general      = data.get("general", {})
    comisiones   = data.get("comisiones", [])
    seguimientos = data.get("seguimientos", [])

    # Format seguimientos (chronological acts)
    actos = []
    for s in reversed(seguimientos):
        actos.append({
            "fecha":     s.get("fecha", "")[:10],
            "estado":    s.get("desEstado", ""),
            "comision":  s.get("desComisiones") or "",
            "detalle":   (s.get("detalle") or "")[:200],
            "archivos":  [a.get("nombreArchivo","") for a in s.get("archivos",[]) if a.get("activo")],
        })

    # Detect predictamen / dictamen
    dictamen = next(
        (a for s in seguimientos for a in s.get("archivos", [])
         if "dictamen" in (a.get("descripcion") or "").lower()
         or "dictamen" in (a.get("nombreArchivo") or "").lower()),
        None,
    )

    return {
        "numero":           general.get("proyectoLey", numero),
        "titulo":           general.get("titulo", ""),
        "estado":           general.get("desEstado", ""),
        "grupo_parlamentario": general.get("desGpar", ""),
        "proponente":       general.get("desProponente", ""),
        "legislatura":      general.get("desLegis", ""),
        "comisiones":       [c["nombre"] for c in comisiones],
        "actos":            actos,
        "predictamen":      {
            "fecha":    dictamen.get("fecha", "")[:10] if dictamen else None,
            "archivo":  dictamen.get("nombreArchivo") if dictamen else None,
        } if dictamen else None,
        "fases":            [f["fase"] for f in data.get("fases", []) if f.get("tipo") in (1, 2)],
        "fuente":           f"SPLEY expediente — {SPLEY_API}",
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

        # Síntesis dentro del rango [hoy, hoy+dias]; si no hay, la más reciente
        en_rango = [e for e in entradas if today <= e["fecha"] <= limite]
        vigentes = en_rango or entradas[:1]
        nota = None if en_rango else (
            "No hay síntesis publicada para los próximos días; "
            "se muestra la más reciente disponible."
        )

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
    Busca mociones de interpelación presentadas contra ministros,
    incluyendo las que están juntando firmas.
    `ministro` filtra opcionalmente por nombre del ministro o cartera.
    """
    import asyncio

    base = f"interpelación {ministro} " if ministro else "interpelación ministro "
    queries = [
        f"moción {base}congreso peru 2026",
        f"{base}congreso peru firmas",
    ]
    tasks = [_google_news(q, max_results=8) for q in queries]
    resultados = await asyncio.gather(*tasks)

    seen, items = set(), []
    for lista in resultados:
        for n in lista:
            if n["enlace"] not in seen:
                seen.add(n["enlace"])
                items.append(n)

    # Also scrape congreso destacados for interpelaciones
    try:
        async with _client() as c:
            r = await c.get("https://www.congreso.gob.pe/home/")
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a[href]"):
                text = a.get_text(strip=True).lower()
                if "interpelac" in text or "moción" in text:
                    enlace = a.get("href", "")
                    titulo = a.get_text(strip=True)
                    if enlace not in seen and titulo:
                        seen.add(enlace)
                        items.insert(0, {"titulo": titulo, "enlace": enlace, "fuente": "congreso.gob.pe"})
    except Exception:
        pass

    if not items:
        return {"sin_datos": True,
                "mensaje": "No se encontraron mociones de interpelación activas en este momento."}

    return {
        "fuente": "Google News + congreso.gob.pe",
        "total": len(items),
        "interpelaciones": items,
    }
