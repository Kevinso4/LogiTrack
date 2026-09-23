"""CORS desde configuración, sin `["*"]` (defecto 1.5)."""

from app.config import Settings


def test_el_cors_por_defecto_es_el_origen_del_frontend():
    ajustes = Settings()
    assert ajustes.cors_origins == [
        "http://localhost:5173",
        "http://localhost:4173",
    ]


def test_el_cors_se_puede_configurar_por_entorno(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", '["http://otro-origen.test"]')
    ajustes = Settings()
    assert ajustes.cors_origins == ["http://otro-origen.test"]
