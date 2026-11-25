"""Testes da API do Mensura: contrato, regras de negócio, cache e segurança."""
import importlib
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    """Carrega a API com cache SQLite isolado em pasta temporária."""
    monkeypatch.setenv("RENDER", "1")  # força o cache para a pasta temporária
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    for m in ("backend.main", "backend.mensura_cache_jsonld"):
        sys.modules.pop(m, None)
    mod = importlib.import_module("backend.main")
    return mod


@pytest.fixture()
def client(app_mod):
    return TestClient(app_mod.app)


def _ofertas_fake(mod, n=3):
    return [
        mod.OfertaWeb(
            id_externo=str(i), titulo=f"Item {i}", preco=p, frete_gratis=i % 2 == 0,
            logistica_full=False, prazo_estimado_dias=3, vendedor="Loja", loja_origem="Loja",
            condicao_pagamento="Pix", link_compra=f"https://loja.com.br/{i}", disponivel_estoque=1,
        )
        for i, p in enumerate([30.0, 10.0, 20.0][:n])
    ]


# ---------- Contrato básico ----------

def test_status_online(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert r.json()["status"] == "online"


def test_frontend_servido_na_raiz(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>" in r.text and "Mensura" in r.text


@pytest.mark.parametrize("params", ["q=a", "q=soja&limite=0", "q=soja&limite=51"])
def test_busca_valida_parametros(client, params):
    assert client.get(f"/api/ml/buscar?{params}").status_code == 422


def test_busca_sem_chave_nao_inventa_ofertas(client):
    r = client.get("/api/ml/buscar?q=soja")
    assert r.status_code == 200
    assert r.json() == []


def test_contingencia_so_quando_pedida(client):
    r = client.get("/api/ml/buscar?q=soja&permitir_contingencia=true")
    assert r.status_code == 200
    assert len(r.json()) == 3
    assert r.headers["X-Mensura-Search-Source"] == "contingencia"


def test_busca_ordena_por_preco_e_usa_cache(client, app_mod, monkeypatch):
    chamadas = {"n": 0}

    async def fake(termo, limite, regiao=""):
        chamadas["n"] += 1
        return _ofertas_fake(app_mod)

    monkeypatch.setenv("SERPER_API_KEY", "teste")
    monkeypatch.setattr(app_mod, "buscar_google_shopping_serper", fake)
    r1 = client.get("/api/ml/buscar?q=Soja Grão")
    assert [o["preco"] for o in r1.json()] == [10.0, 20.0, 30.0]
    assert r1.headers["X-Mensura-Cache"] == "MISS"
    r2 = client.get("/api/ml/buscar?q=  soja   grão ")
    assert r2.headers["X-Mensura-Cache"] == "HIT"
    assert chamadas["n"] == 1


def test_contingencia_nao_entra_no_cache(client):
    """Dados de contingência (simulados) nunca podem ser servidos do cache como se fossem ofertas reais."""
    client.get("/api/ml/buscar?q=sal&permitir_contingencia=true")
    assert client.get("/api/cache/status").json()["entradas_ativas"] == 0
    r = client.get("/api/ml/buscar?q=sal")
    assert r.headers.get("X-Mensura-Cache") != "HIT"
    assert r.json() == []


# ---------- Regras de negócio ----------

@pytest.mark.parametrize("entrada,esperado", [
    ("R$ 1.234,56", 1234.56), ("$ 1,234.56", 1234.56), ("R$ 9,9", 9.9), ("12", 12.0),
    ("1.000", 1000.0), ("", 0.0), (None, 0.0), ("grátis", 0.0), (-5, 0.0), (3.456, 3.46),
])
def test_limpar_preco(app_mod, entrada, esperado):
    assert app_mod._limpar_preco_br(entrada) == esperado


@pytest.mark.parametrize("entrada,esperado", [
    ("", ""), ("Brasil todo", ""), ("Nordeste", "Recife, State of Pernambuco, Brazil"),
    ("Recife, PE", "Recife, State of Pernambuco, Brazil"), ("Curitiba", "Curitiba, Brazil"),
])
def test_regiao_serper(app_mod, entrada, esperado):
    assert app_mod._normalizar_location_serper(entrada) == esperado


# ---------- Segurança ----------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",  # metadados da nuvem
    "http://10.0.0.5/",
    "http://192.168.0.1/",
    "http://[::1]/",
    "http://exemplo.internal/",
    "http://user:senha@example.com/",
    "http://example.com:8080/",
    "file:///etc/passwd",
    "ftp://example.com/",
])
def test_extrair_url_bloqueia_ssrf(client, url):
    r = client.get("/api/extrair-url", params={"url": url})
    assert r.status_code == 400, r.text


def test_extrair_url_bloqueia_redirecionamento_para_rede_interna(app_mod, monkeypatch):
    """Um site público que redireciona para 127.0.0.1 deve ser barrado no segundo salto."""
    cj = sys.modules["backend.mensura_cache_jsonld"]
    resolver = getattr(cj, "_resolver_ip_publico", None)
    assert resolver is not None, "validação de IP público ausente"
    with pytest.raises(ValueError):
        resolver("http://127.0.0.1/admin")


def test_limpar_cache_exige_token(client, monkeypatch):
    assert client.delete("/api/cache/limpar").status_code == 403
    monkeypatch.setenv("MENSURA_ADMIN_TOKEN", "segredo-forte")
    assert client.delete("/api/cache/limpar", headers={"X-Admin-Token": "errado"}).status_code == 403
    r = client.delete("/api/cache/limpar", headers={"X-Admin-Token": "segredo-forte"})
    assert r.status_code == 200 and r.json()["ok"] is True


def test_erro_502_nao_vaza_detalhes_internos(client, monkeypatch):
    cj = sys.modules["backend.mensura_cache_jsonld"]

    async def falha(url, timeout=10.0):
        raise cj.CurlError("conexao recusada em 10.1.2.3:443 /segredo")

    monkeypatch.setattr(cj, "extrair_ofertas_jsonld", falha)
    r = client.get("/api/extrair-url", params={"url": "https://example.com/"})
    assert r.status_code == 502
    assert "10.1.2.3" not in r.text


def test_cors_nao_envia_credenciais(client):
    r = client.get("/api/status", headers={"Origin": "https://malicioso.example"})
    assert r.headers.get("access-control-allow-credentials") != "true"
