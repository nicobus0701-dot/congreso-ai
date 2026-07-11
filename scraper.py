"""
Scrapers for Congreso de la República del Perú.
Tries JSON APIs first, falls back to HTML parsing.
"""
import httpx
from bs4 import BeautifulSoup
import json
from datetime import datetime

TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-PE,es;q=0.9",
}

SPLEY_API  = "https://wb2server.congreso.gob.pe/spley-portal-back/api"
SESIONES_API = "https://wb2server.congreso.gob.pe/visor-sesiones-back/api"
CONGRESO   = "https://www.congreso.gob.pe"


# ── Helpers ────────────────────────────────────────────────────

def _client():
    return httpx.AsyncClient(timeout=TIMEOUT, verify=False,
                             follow_redirects=True, headers=HEADERS)

def _fmt_date(s):
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s), fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    return str(s)[:10] if s else ""

def _parse_html_table(table):
    rows = table.find_all("tr")
    if not rows:
        return []
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    result = []
    for row in rows[1:]:
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if cells:
            result.append(dict(zip(headers, cells)))
    return result


# ── Proyectos de ley ───────────────────────────────────────────

async def fetch_proyectos(autor=None, comision=None, numero=None,
                          legislatura="2021-2026", limit=20):
    async with _client() as c:

        # 1. SPLEY REST API (POST search)
        try:
            payload = {"legislatura": legislatura, "pagina": 1,
                       "registrosPorPagina": limit}
            if autor:   payload["autor"]   = autor
            if comision: payload["comision"] = comision
            if numero:  payload["numero"]  = numero
            r = await c.post(f"{SPLEY_API}/expediente/search",
                             json=payload)
            if r.status_code == 200:
                d = r.json()
                items = (d.get("content") or d.get("data") or
                         d.get("expedientes") or d.get("result") or [])
                if items:
                    return _format_proyectos(items[:limit])
        except Exception:
            pass

        # 2. SPLEY REST API (GET list)
        try:
            params = {"pagina": 1, "registrosPorPagina": limit,
                      "legislatura": legislatura}
            if autor:   params["autor"]   = autor
            if comision: params["comision"] = comision
            r = await c.get(f"{SPLEY_API}/expediente", params=params)
            if r.status_code == 200:
                d = r.json()
                items = (d.get("content") or d.get("data") or [])
                if items:
                    return _format_proyectos(items[:limit])
        except Exception:
            pass

        # 3. Fallback: HTML of congreso.gob.pe/pley/
        try:
            r = await c.get(f"{CONGRESO}/pley/{legislatura}/")
            soup = BeautifulSoup(r.text, "html.parser")
            table = soup.find("table")
            if table:
                rows = _parse_html_table(table)
                if rows:
                    return {"fuente": "congreso.gob.pe (HTML)",
                            "total": len(rows), "items": rows[:limit]}
        except Exception:
            pass

        return {"error": "No se pudo conectar con el sistema SPLEY del Congreso. "
                "Intenta en https://wb2server.congreso.gob.pe/spley-portal/"}


def _format_proyectos(items):
    out = []
    for p in items:
        out.append({
            "numero":   p.get("numero") or p.get("nroExpediente") or "",
            "fecha":    _fmt_date(p.get("fechaPresentacion") or p.get("fecha") or ""),
            "sumilla":  (p.get("sumilla") or p.get("titulo") or "")[:120],
            "autor":    p.get("autor") or p.get("congresista") or "",
            "grupo":    p.get("grupoParlamentario") or p.get("grupo") or "",
            "comision1": p.get("comision1") or p.get("comision") or "",
            "comision2": p.get("comision2") or "",
        })
    return {"fuente": "SPLEY API", "total": len(out), "items": out}


# ── Sesiones ───────────────────────────────────────────────────

async def fetch_sesiones(comision=None, fecha=None, limit=20):
    async with _client() as c:

        # 1. Visor-sesiones API
        try:
            params = {"pagina": 1, "registrosPorPagina": limit}
            if comision: params["comision"] = comision
            if fecha:    params["fecha"]    = fecha
            r = await c.get(f"{SESIONES_API}/sesion/listar", params=params)
            if r.status_code == 200:
                d = r.json()
                items = d.get("content") or d.get("data") or d.get("sesiones") or []
                if items:
                    return _format_sesiones(items[:limit])
        except Exception:
            pass

        # 2. Alternative visor endpoint
        try:
            r = await c.get(f"{SESIONES_API}/sesion", params={"size": limit})
            if r.status_code == 200:
                d = r.json()
                items = d.get("content") or d.get("data") or []
                if items:
                    return _format_sesiones(items[:limit])
        except Exception:
            pass

        # 3. Fallback: HTML
        try:
            r = await c.get(f"{CONGRESO}/comisiones2020/")
            soup = BeautifulSoup(r.text, "html.parser")
            items = []
            for a in soup.select("a[href*='sesion'], a[href*='Sesion']")[:limit]:
                items.append({"comision": a.get_text(strip=True),
                              "enlace": CONGRESO + a.get("href", "")})
            if items:
                return {"fuente": "congreso.gob.pe (HTML)",
                        "total": len(items), "items": items}
        except Exception:
            pass

        return {"error": "No se pudo conectar con el visor de sesiones. "
                "Intenta en https://wb2server.congreso.gob.pe/visor-sesiones/"}


def _format_sesiones(items):
    out = []
    for s in items:
        out.append({
            "comision": s.get("comision") or s.get("nombreComision") or "",
            "fecha":    _fmt_date(s.get("fecha") or s.get("fechaSesion") or ""),
            "hora":     s.get("hora") or s.get("horaSesion") or "",
            "proyecto": (s.get("proyectoSustentado") or s.get("agenda") or "")[:100],
            "dictamen": s.get("dictamen") or "",
            "votacion": s.get("votacion") or s.get("resultado") or "",
            "acuerdo":  s.get("acuerdo") or "",
        })
    return {"fuente": "Visor Sesiones API", "total": len(out), "items": out}


# ── Agenda ─────────────────────────────────────────────────────

async def fetch_agenda():
    async with _client() as c:

        # 1. Try JSON agenda endpoint
        try:
            r = await c.get(f"{CONGRESO}/Agenda/GetAgenda.ashx")
            if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
                return {"fuente": "congreso.gob.pe/Agenda", "items": r.json()}
        except Exception:
            pass

        # 2. Scrape HTML agenda page
        try:
            r = await c.get(f"{CONGRESO}/Agenda/")
            soup = BeautifulSoup(r.text, "html.parser")
            items = []

            for row in soup.select("table tr")[1:30]:
                cells = row.find_all("td")
                if len(cells) >= 3:
                    link_tag = row.find("a")
                    items.append({
                        "camara":  cells[0].get_text(strip=True) if len(cells) > 0 else "",
                        "sesion":  cells[1].get_text(strip=True) if len(cells) > 1 else "",
                        "fecha":   cells[2].get_text(strip=True) if len(cells) > 2 else "",
                        "hora":    cells[3].get_text(strip=True) if len(cells) > 3 else "",
                        "sala":    cells[4].get_text(strip=True) if len(cells) > 4 else "",
                        "enlace":  link_tag["href"] if link_tag and link_tag.get("href") else "",
                    })

            if items:
                return {"fuente": "congreso.gob.pe/Agenda (HTML)",
                        "total": len(items), "items": items}

            # No table — return raw text
            text = soup.get_text(separator="\n", strip=True)
            return {"fuente": "congreso.gob.pe/Agenda",
                    "contenido_texto": text[:3000]}
        except Exception as e:
            pass

        return {"error": "No se pudo obtener la agenda. "
                "Consulta https://www.congreso.gob.pe/Agenda/"}


# ── Destacados ─────────────────────────────────────────────────

async def fetch_destacados():
    async with _client() as c:
        try:
            r = await c.get(f"{CONGRESO}/noticias/")
            soup = BeautifulSoup(r.text, "html.parser")
            items = []

            for art in soup.select("article, .noticia, .item-noticia, .news-item")[:15]:
                title_el = art.find(["h2", "h3", "h4", "a"])
                link_el  = art.find("a")
                date_el  = art.find(["time", ".fecha", ".date"])
                desc_el  = art.find("p")
                items.append({
                    "titulo":  title_el.get_text(strip=True) if title_el else "",
                    "fecha":   date_el.get_text(strip=True) if date_el else "",
                    "resumen": desc_el.get_text(strip=True)[:200] if desc_el else "",
                    "enlace":  (CONGRESO + link_el["href"]
                                if link_el and link_el.get("href", "").startswith("/")
                                else link_el.get("href", "") if link_el else ""),
                })

            items = [i for i in items if i["titulo"]]
            if items:
                return {"fuente": "congreso.gob.pe/noticias",
                        "total": len(items), "items": items}

            # Fallback: any links from home
            r2 = await c.get(f"{CONGRESO}/")
            soup2 = BeautifulSoup(r2.text, "html.parser")
            links = []
            for a in soup2.find_all("a", href=True)[:30]:
                txt = a.get_text(strip=True)
                if len(txt) > 20:
                    href = a["href"]
                    if href.startswith("/"):
                        href = CONGRESO + href
                    links.append({"titulo": txt, "enlace": href})
            return {"fuente": "congreso.gob.pe (homepage)",
                    "total": len(links), "items": links[:15]}
        except Exception as e:
            return {"error": f"No se pudo obtener destacados: {e}"}
