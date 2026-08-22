"""Rutas de páginas y estado del servicio."""
import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from config import LLM_API_KEY, STATIC_DIR, static_file
from scraper import fetch_agenda_camaras, fetch_destacados, fetch_proyectos

router = APIRouter()


@router.get("/status")
async def status():
    return {"ready": bool(LLM_API_KEY)}


# Estructura fija de comisiones ordinarias (ver scraper.COMISIONES_SENADO /
# COMISIONES_DIPUTADOS) — no es "actividad", así que la tarjeta se llama
# "registradas", no "activas": es un conteo que no cambia semana a semana.
_TOTAL_COMISIONES_SENADO    = 7
_TOTAL_COMISIONES_DIPUTADOS = 16

_MESES_CORTOS = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _parse_fecha_hora(fecha: str, hora: str) -> datetime | None:
    """'04/08/2026' + '9:00 AM' -> datetime. None si el formato no calza."""
    try:
        dt_fecha = datetime.strptime(fecha, "%d/%m/%Y")
        dt_hora = datetime.strptime(hora.strip().upper().replace(" ", ""), "%I:%M%p")
        return dt_fecha.replace(hour=dt_hora.hour, minute=dt_hora.minute)
    except (ValueError, AttributeError):
        return None


# Cache en memoria con TTL: fetch_proyectos y fetch_agenda_camaras pegan a
# servidores reales del Congreso que son lentos e inconsistentes (8-25s
# medido en vivo, sin relación con nuestro código — ver fetch_proyectos).
# Nada de esto cambia minuto a minuto, así que no vale la pena pagar ese
# costo en cada apertura de un chat nuevo: se recalcula cada 5 minutos y el
# resto de las veces se sirve al toque desde acá.
_METRICS_CACHE = {"data": None, "expira": None}
_METRICS_TTL_SEGUNDOS = 300


@router.get("/dashboard-metrics")
async def dashboard_metrics():
    """
    Las 4 métricas de la pantalla de bienvenida. Cada una sale de una fuente
    real (mismos scrapers que usa el chat) — nada de números fijos ni
    inventados. Si una fuente falla, esa tarjeta se omite en vez de mostrar
    un dato falso.
    """
    ahora_cache = datetime.now()
    if _METRICS_CACHE["data"] is not None and ahora_cache < _METRICS_CACHE["expira"]:
        return _METRICS_CACHE["data"]

    agenda, proyectos, destacados = await asyncio.gather(
        fetch_agenda_camaras(dias=14),
        fetch_proyectos(dias=7),
        fetch_destacados(),
        return_exceptions=True,
    )

    proxima_sesion = None
    if isinstance(agenda, dict) and not agenda.get("sin_datos"):
        ahora = datetime.now()
        futuras = []
        for s in agenda.get("sesiones", []):
            dt = _parse_fecha_hora(s.get("fecha", ""), s.get("hora", ""))
            if dt and dt >= ahora:
                futuras.append((dt, s))
        if futuras:
            futuras.sort(key=lambda par: par[0])
            dt, s = futuras[0]
            if dt.date() == ahora.date():
                etiqueta = "Hoy"
            elif (dt.date() - ahora.date()).days == 1:
                etiqueta = "Mañana"
            else:
                etiqueta = f"{dt.day} {_MESES_CORTOS[dt.month]}"
            proxima_sesion = {
                "etiqueta_fecha": etiqueta,
                "hora": s.get("hora", ""),
                "camara": s.get("camara", ""),
                "tema": s.get("tema", ""),
            }

    proyectos_ingresados = None
    if isinstance(proyectos, dict):
        # `total` es cuántos DEVOLVIÓ el scraper, recortado por `limit` (20 por
        # defecto); `total_disponible` es cuántos hay de verdad y solo aparece
        # cuando hubo recorte (ver _format_proyectos). Esta tarjeta dice
        # "proyectos ingresados en 7 días", así que le toca el número real:
        # leyendo `total` mostraba 20 cuando eran 48 — un dato falso en la
        # pantalla de inicio, y encima el chat contestaba 48 a la misma
        # pregunta porque el modelo sí veía `total_disponible`.
        total_real = proyectos.get("total_disponible") or proyectos.get("total", 0)
        proyectos_ingresados = {"total": total_real, "dias": 7}

    citaciones_links = set()
    if isinstance(destacados, dict):
        for datos_camara in destacados.get("camaras", {}).values():
            if not isinstance(datos_camara, dict):
                continue
            for cit in datos_camara.get("citaciones", []):
                enlace = cit.get("enlace")
                if enlace:
                    citaciones_links.add(enlace)

    resultado = {
        "proxima_sesion": proxima_sesion,
        "proyectos_ingresados": proyectos_ingresados,
        "comisiones_registradas": {
            "total": _TOTAL_COMISIONES_SENADO + _TOTAL_COMISIONES_DIPUTADOS,
            "senado": _TOTAL_COMISIONES_SENADO,
            "diputados": _TOTAL_COMISIONES_DIPUTADOS,
        },
        "citaciones": {"total": len(citaciones_links)},
    }
    _METRICS_CACHE["data"] = resultado
    _METRICS_CACHE["expira"] = ahora_cache + timedelta(seconds=_METRICS_TTL_SEGUNDOS)
    return resultado


@router.get("/", response_class=HTMLResponse)
async def root():
    return static_file("index.html")


@router.get("/static/sw.js")
async def service_worker():
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )
