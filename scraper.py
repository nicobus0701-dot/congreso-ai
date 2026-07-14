"""
Scrapers for Congreso de la República del Perú.
- Proyectos de ley: SPLEY API (api.congreso.gob.pe/spley-portal-service)
- Sesiones / Agenda / Destacados: DuckDuckGo news + fallback HTML
"""
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

async def fetch_proyectos(autor=None, comision=None, numero=None,
                          legislatura="2021-2026", limit=20):
    async with _client() as c:

        # Build payload for SPLEY API
        payload: dict = {"perParId": PER_PAR_ID, "page": 0, "size": limit}

        if numero:
            payload["strBusqueda"] = numero
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
    query = "congreso perú noticias destacados sesión pleno ley 2026"
    noticias = await _google_news(query, max_results=15)

    if noticias:
        return {
            "fuente": "Noticias recientes (DuckDuckGo)",
            "total": len(noticias),
            "items": noticias,
        }

    return {
        "error": "No se pudo obtener las noticias del Congreso."
    }


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
    async with _client() as c:
        payload = {
            "perParId":    PER_PAR_ID,
            "strBusqueda": numero,
            "page":        0,
            "size":        5,
        }
        try:
            r = await c.post(f"{SPLEY_API}/proyecto-ley/lista-con-filtro", json=payload)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("proyectos", [])
                if items:
                    p   = items[0]
                    num = p.get("pleyNum") or ""
                    return {
                        "numero":       p.get("proyectoLey") or num,
                        "titulo":       p.get("titulo") or "",
                        "estado":       p.get("desEstado") or "",
                        "fecha_ingreso": _fmt_date(p.get("fecPresentacion") or ""),
                        "autor":        p.get("autores") or p.get("desProponente") or "",
                        "comision":     p.get("desComision") or "",
                        "sumilla":      p.get("sumilla") or p.get("titulo") or "",
                        "enlace":       f"{SPLEY_PORTAL}/{num}" if num else "",
                        "fuente":       "SPLEY — api.congreso.gob.pe",
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


async def fetch_transcript_youtube(video_id: str):
    """Obtiene el transcript automático de YouTube para un video dado."""
    import asyncio
    from youtube_transcript_api import YouTubeTranscriptApi

    def _get():
        api = YouTubeTranscriptApi()
        # Intentar en español primero, luego cualquier idioma disponible
        for langs in (["es"], ["es-419"], None):
            try:
                if langs:
                    tr = api.fetch(video_id, languages=langs)
                else:
                    # listar y tomar el primero disponible
                    tl   = api.list(video_id)
                    first = next(iter(tl))
                    tr   = api.fetch(video_id, languages=[first.language_code])
                text = " ".join(s.text for s in tr.snippets)
                if text.strip():
                    return {"ok": True, "text": text[:40000], "entries": len(tr.snippets)}
            except Exception:
                continue
        return {"ok": False, "error": "No hay subtítulos disponibles para este video todavía. Intenta más tarde."}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get)
