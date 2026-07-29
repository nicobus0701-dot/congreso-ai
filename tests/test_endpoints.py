"""
Tests de humo para los 4 endpoints críticos.
Requieren: pytest httpx pytest-asyncio  (asyncio_mode = auto en pytest.ini)
"""
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Evitar que el servidor necesite GROQ_API_KEY real para arrancar
os.environ.setdefault("GROQ_API_KEY", "test-key-mock")

from server import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── /status ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_status_ok(client):
    r = await client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert "ready" in data
    assert isinstance(data["ready"], bool)


# ── / (index.html) ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_root_returns_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "<html" in r.text.lower()


# ── /congreso-proyectos ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_congreso_proyectos_shape(client):
    fake_data = {
        "items": [
            {
                "numero": "1234/2024",
                "sumilla": "Proyecto de prueba",
                "enlace": "https://wb2server.congreso.gob.pe/spley-portal/#/expediente/1234",
            }
        ]
    }
    with patch("server.fetch_proyectos", new=AsyncMock(return_value=fake_data)):
        r = await client.get("/congreso-proyectos")
    assert r.status_code == 200
    data = r.json()
    # El endpoint devuelve {"pdfs": [...]} (misma clave que /congreso-pdfs)
    assert "pdfs" in data
    assert isinstance(data["pdfs"], list)
    assert data["pdfs"][0]["tipo"] == "Proyecto de Ley"


# ── /congreso-pdfs ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_congreso_pdfs_shape(client):
    fake_destacados = {
        "destacados": [
            {"titulo": "Informe PDF", "enlace": "https://example.com/doc.pdf"},
        ],
        "citaciones": [],
    }
    with patch("server.fetch_destacados", new=AsyncMock(return_value=fake_destacados)):
        r = await client.get("/congreso-pdfs")
    assert r.status_code == 200
    data = r.json()
    assert "pdfs" in data
    assert isinstance(data["pdfs"], list)
