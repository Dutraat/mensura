"""API de busca de produtos e preços do Mensura."""

import json
import os
import re
import socket
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.mensura_cache_jsonld import registrar_rotas_e_cache

load_dotenv()

try:
    from curl_cffi import CurlOpt
    from curl_cffi import requests as cffi_requests
    HAS_CFFI = True
except ImportError:
    HAS_CFFI = False

import httpx


app = FastAPI(
    title="Mensura Shopping API",
    description="Busca de produtos e preços no Google Shopping via Serper",
    version="1.4.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"


class OfertaWeb(BaseModel):
    id_externo: str
    titulo: str
    preco: float
    frete_gratis: bool
    logistica_full: bool
    prazo_estimado_dias: int
    vendedor: str
    loja_origem: str = "Mercado Livre"
    site_dominio: Optional[str] = None
    condicao_pagamento: str
    link_compra: str
    url_imagem: Optional[str] = None
    disponivel_estoque: int


@app.get("/", include_in_schema=False)
async def frontend():
    return FileResponse(FRONTEND_INDEX)


def _limpar_preco_br(valor) -> float:
    # Converte textos de preco em formato BR (R$ 1.234,56) ou US ($ 1,234.56) para float.
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return round(float(valor), 2) if valor > 0 else 0.0
    texto = str(valor).strip()
    if not texto:
        return 0.0
    m = re.search(r"\d[\d.,]*", texto)
    if not m:
        return 0.0
    num = m.group(0).strip(".,")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        partes = num.split(",")
        if len(partes) == 2 and len(partes[1]) in (1, 2):
            num = partes[0] + "." + partes[1]
        else:
            num = num.replace(",", "")
    elif "." in num:
        partes = num.split(".")
        if len(partes) == 2 and len(partes[1]) in (1, 2):
            pass
        else:
            num = num.replace(".", "")
    try:
        val = float(num)
        return round(val, 2) if val > 0 else 0.0
    except ValueError:
        return 0.0


def _normalizar_location_serper(regiao: str) -> str:
    """Converte entrada amigavel (ex: 'Recife, PE') em formato location aceito pela Serper."""
    r = (regiao or "").strip()
    if not r or r.lower() in ("brasil", "brasil todo", "br", "todas", "todos"):
        return ""
    mapa_uf = {
        "AC": "Acre", "AL": "Alagoas", "AP": "Amapa", "AM": "Amazonas",
        "BA": "Bahia", "CE": "Ceara", "DF": "Federal District", "ES": "Espirito Santo",
        "GO": "Goias", "MA": "Maranhao", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul",
        "MG": "Minas Gerais", "PA": "Para", "PB": "Paraiba", "PR": "Parana",
        "PE": "Pernambuco", "PI": "Piaui", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
        "RS": "Rio Grande do Sul", "RO": "Rondonia", "RR": "Roraima", "SC": "Santa Catarina",
        "SP": "Sao Paulo", "SE": "Sergipe", "TO": "Tocantins",
    }
    m = re.match(r"^([^,/-]+)[,\s/-]+([A-Za-z]{2})$", r)
    if m:
        cidade = m.group(1).strip()
        uf = m.group(2).upper()
        estado = mapa_uf.get(uf, uf)
        return f"{cidade}, State of {estado}, Brazil"
    if "brazil" not in r.lower() and "brasil" not in r.lower():
        return f"{r}, Brazil"
    return r


async def buscar_google_shopping_serper(
    termo: str, limite: int, regiao: str = ""
) -> List[OfertaWeb]:
    api_key = os.getenv("SERPER_API_KEY", "")
    payload = {"q": termo, "gl": "br", "hl": "pt-br", "num": limite}
    loc = _normalizar_location_serper(regiao)
    if loc:
        payload["location"] = loc

    async with httpx.AsyncClient(timeout=20.0) as client:
        resposta = await client.post(
            "https://google.serper.dev/shopping",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resposta.raise_for_status()
        dados = resposta.json()

    ofertas: List[OfertaWeb] = []
    for idx, item in enumerate(dados.get("shopping", [])[:limite]):
        preco = _limpar_preco_br(item.get("price", ""))
        if preco <= 0:
            continue

        fonte = item.get("source") or "Loja Online"
        entrega = str(item.get("delivery") or "").lower()
        frete_gratis = "grátis" in entrega or "gratis" in entrega
        link_item = item.get("link", "")
        host = ""
        try:
            host = (urlparse(link_item).netloc or "").lower().replace("www.", "")
        except Exception:
            host = ""
        ofertas.append(
            OfertaWeb(
                id_externo=str(item.get("productId") or item.get("position") or idx),
                titulo=item.get("title", ""),
                preco=preco,
                frete_gratis=frete_gratis,
                logistica_full="full" in entrega,
                prazo_estimado_dias=3 if frete_gratis else 5,
                vendedor=fonte,
                loja_origem=fonte,
                site_dominio=host or fonte,
                condicao_pagamento="À vista (ver na loja)",
                link_compra=link_item,
                url_imagem=item.get("imageUrl"),
                disponivel_estoque=10,
            )
        )
    return ofertas


def _gerar_fallback_simulacao_realista(
    termo: str,
    limite: int
) -> List[OfertaWeb]:
    termo_limpo = termo.strip().title()
    slug = quote_plus(termo.strip().replace(" ", "-"))
    link_base = f"https://lista.mercadolivre.com.br/{slug}"
    t_low = termo.lower()
    if "soja" in t_low:
        base_preco = 4.10
    elif "alcool" in t_low or "álcool" in t_low:
        base_preco = 9.40
    elif "sal" in t_low:
        base_preco = 1.85
    elif "shoyu" in t_low:
        base_preco = 14.20
    elif "pote" in t_low or "embalagem" in t_low:
        base_preco = 0.36
    else:
        base_preco = 45.90

    variacoes = [
        ("Distribuidora Nacional ML", 0.96, True, True, 2, "Até 10x sem juros"),
        ("Atacado Express Brasil", 1.00, True, False, 4, "À vista ou 3x sem juros"),
        ("Comercial Suprimentos Web", 1.05, False, False, 5, "À vista"),
    ]
    ofertas = []
    for idx, (vend, fator, fg, full, prazo, pgto) in enumerate(variacoes[:limite]):
        ofertas.append(
            OfertaWeb(
                id_externo=f"MLBSIM{1000+idx}",
                titulo=f"{termo_limpo} - Lote Comercial ({idx+1})",
                preco=round(base_preco * fator, 2),
                frete_gratis=fg,
                logistica_full=full,
                prazo_estimado_dias=prazo,
                vendedor=f"ML • {vend}",
                loja_origem="Mercado Livre",
                site_dominio="mercadolivre.com.br",
                condicao_pagamento=pgto,
                link_compra=link_base,
                url_imagem=None,
                disponivel_estoque=50,
            )
        )
    return ofertas


@app.get("/api/status")
async def status_api():
    return {
        "status": "online",
        "servico": "Mensura Buscador",
        "versao": "1.4.0",
        "fonte_busca": "Google Shopping (Serper)",
        "camuflagem_tls_ativa": HAS_CFFI
    }


@app.get("/api/ml/buscar", response_model=List[OfertaWeb])
async def rota_buscar_ml(
    response: Response,
    q: str = Query(..., min_length=2, description="Produto para pesquisar"),
    limite: int = Query(10, ge=1, le=50),
    regiao: str = Query("", description="Cidade/UF para priorizar ofertas regionais (ex: Recife, PE)"),
    permitir_contingencia: bool = Query(
        False,
        description="Usa dados de contingência quando o Serper não está disponível"
    )
):
    ofertas: List[OfertaWeb] = []
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    serper_falhou = not api_key
    if api_key:
        try:
            ofertas = await buscar_google_shopping_serper(q, limite, regiao=regiao)
            response.headers["X-Mensura-Search-Source"] = "serper"
        except Exception as e:
            serper_falhou = True
            print(f"[ERRO SERPER SHOPPING] {e}")
    else:
        print("[ERRO SERPER SHOPPING] SERPER_API_KEY não está definida.")

    if serper_falhou and permitir_contingencia:
        print(f"[AVISO SERPER] Usando contingência para '{q}'.")
        ofertas = _gerar_fallback_simulacao_realista(q, limite)
        response.headers["X-Mensura-Search-Source"] = "contingencia"

    ofertas.sort(key=lambda x: (x.preco, not x.frete_gratis))
    return ofertas


registrar_rotas_e_cache(app)
