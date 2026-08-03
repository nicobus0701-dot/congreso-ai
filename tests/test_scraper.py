"""
Tests de funciones puras del scraper — sin red, sin VCR.
"""
from datetime import date

import pytest

from scraper import estado_legislativo, estado_legislativo_texto


@pytest.mark.parametrize("hoy,en_legislatura,legislatura", [
    # Primera Legislatura Ordinaria: 27 jul → 15 dic
    (date(2026, 7, 27), True, "Primera Legislatura Ordinaria"),   # primer día
    (date(2026, 8, 2), True, "Primera Legislatura Ordinaria"),    # confirmado en vivo
    (date(2026, 12, 15), True, "Primera Legislatura Ordinaria"),  # último día
    # Receso entre legislaturas: 16 dic → último día de feb
    (date(2026, 12, 16), False, None),
    (date(2027, 1, 15), False, None),
    (date(2027, 2, 28), False, None),
    # Segunda Legislatura Ordinaria: 1 mar → 15 jun
    (date(2027, 3, 1), True, "Segunda Legislatura Ordinaria"),
    (date(2027, 6, 15), True, "Segunda Legislatura Ordinaria"),
    # Receso antes del próximo período anual: 16 jun → 26 jul
    (date(2027, 6, 16), False, None),
    (date(2027, 7, 26), False, None),
])
def test_estado_legislativo(hoy, en_legislatura, legislatura):
    e = estado_legislativo(hoy)
    assert e["en_legislatura"] is en_legislatura
    assert e["legislatura"] == legislatura


def test_estado_legislativo_cruza_año_en_diciembre():
    """31 dic sigue perteneciendo al período anual que empezó en julio del mismo año."""
    e = estado_legislativo(date(2026, 12, 31))
    assert e["en_legislatura"] is False
    # La próxima legislatura (segunda) empieza en marzo del año siguiente.
    assert e["proxima_legislatura"] == "01/03/2027"


def test_estado_legislativo_cruza_año_en_enero():
    """1 ene ya pertenece al período anual que empezó en julio del año anterior."""
    e = estado_legislativo(date(2027, 1, 1))
    assert e["en_legislatura"] is False
    assert e["proxima_legislatura"] == "01/03/2027"


def test_estado_legislativo_texto_en_sesion():
    texto = estado_legislativo_texto(date(2026, 8, 2))
    assert "en sesión" in texto
    assert "Primera Legislatura Ordinaria" in texto
    assert "15/12/2026" in texto


def test_estado_legislativo_texto_en_receso():
    texto = estado_legislativo_texto(date(2027, 1, 15))
    assert "receso" in texto
    assert "01/03/2027" in texto
