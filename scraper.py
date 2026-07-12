"""
Scrapers for Congreso de la República del Perú.
- Proyectos de ley: SPLEY API (api.congreso.gob.pe/spley-portal-service)
- Sesiones / Agenda / Destacados: DuckDuckGo news + fallback HTML
"""
import httpx
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


def _ddgs_news_sync(query: str, max_results: int = 15):
    """Synchronous DuckDuckGo news search."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return []
    try:
        results = DDGS().news(query, max_results=max_results)
        return [
            {
                "titulo":  r.get("title", ""),
                "fecha":   r.get("date", "")[:10],
                "fuente":  r.get("source", ""),
                "resumen": r.get("body", "")[:300],
                "enlace":  r.get("url", ""),
            }
            for r in (results or [])
            if r.get("title")
        ]
    except Exception:
        return []


async def _ddgs_news(query: str, max_results: int = 15):
    """Run DuckDuckGo news in a thread so it doesn't conflict with the event loop."""
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _ddgs_news_sync, query, max_results)


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

    noticias = await _ddgs_news(query, max_results=limit)

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
    noticias = await _ddgs_news(query, max_results=15)

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
    noticias = await _ddgs_news(query, max_results=15)

    if noticias:
        return {
            "fuente": "Noticias recientes (DuckDuckGo)",
            "total": len(noticias),
            "items": noticias,
        }

    return {
        "error": "No se pudo obtener las noticias del Congreso."
    }
