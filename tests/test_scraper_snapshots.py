"""
Snapshot tests del scraper.

Cada test reproduce una cassette VCR (HTTP real grabado del Congreso) y compara
la estructura parseada contra un snapshot JSON. Sirven para detectar cuándo el
Congreso cambia su HTML/API y el parseo se rompe en silencio.

Solo se cubren funciones deterministas: las que construyen URLs a partir de la
fecha de hoy (fetch_agenda_comisiones, fetch_agenda_camaras) no se pueden grabar
porque la cassette dejaría de coincidir al día siguiente.
"""
import warnings

import pytest

from scraper import (
    fetch_agenda_pleno,
    fetch_destacados,
    fetch_estado_proyecto,
    fetch_expediente,
    fetch_proyectos,
)
from tests.conftest import assert_snapshot

# El scraper usa verify=False a propósito (certs del Congreso).
pytestmark = [
    pytest.mark.filterwarnings("ignore::urllib3.exceptions.InsecureRequestWarning"),
    pytest.mark.vcr,
]

PROYECTO_DEMO = "14864"


@pytest.mark.asyncio
async def test_fetch_proyectos_snapshot():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_proyectos(limit=3)

    assert data.get("items"), "SPLEY no devolvió proyectos"
    assert_snapshot("fetch_proyectos", data)


@pytest.mark.asyncio
async def test_fetch_proyectos_estructura():
    """Contrato mínimo: cada proyecto trae número, título y enlace."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_proyectos(limit=3)

    for item in data["items"]:
        assert item["numero"], "proyecto sin número"
        assert item["titulo"], "proyecto sin título"
        assert item["enlace"].startswith("http"), "enlace inválido"


@pytest.mark.asyncio
async def test_fetch_expediente_snapshot():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_expediente(numero=PROYECTO_DEMO)

    assert_snapshot("fetch_expediente", data)


@pytest.mark.asyncio
async def test_fetch_estado_proyecto_snapshot():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_estado_proyecto(numero=PROYECTO_DEMO)

    assert_snapshot("fetch_estado_proyecto", data)


@pytest.mark.asyncio
async def test_fetch_destacados_snapshot():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_destacados()

    assert_snapshot("fetch_destacados", data)


@pytest.mark.asyncio
async def test_fetch_agenda_pleno_snapshot():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        data = await fetch_agenda_pleno()

    assert_snapshot("fetch_agenda_pleno", data)
