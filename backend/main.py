"""API de busca de produtos e preços do Mensura."""

import json
import os
import re
import socket
from typing import List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    version="1.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class OfertaWeb(BaseModel):
    id_externo: str
    titulo: str
    preco: float
    frete_gratis: bool
    logistica_full: bool
    prazo_estimado_dias: int
    vendedor: str
    loja_origem: str = "Mercado Livre"
    condicao_pagamento: str
    link_compra: str
    url_imagem: Optional[str] = None
    disponivel_estoque: int


def _limpar_preco_br(texto: str) -> float:
    limpo = re.sub(r"[^\d,]", "", str(texto or ""))
    if not limpo:
        return 0.0
    return float(limpo.replace(".", "").replace(",", "."))


async def buscar_google_shopping_serper(
    termo: str, limite: int
) -> List[OfertaWeb]:
    api_key = os.getenv("SERPER_API_KEY", "")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resposta = await client.post(
            "https://google.serper.dev/shopping",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json={"q": termo, "gl": "br", "hl": "pt-br", "num": limite},
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
                condicao_pagamento="À vista (ver na loja)",
                link_compra=item.get("link", ""),
                url_imagem=item.get("imageUrl"),
                disponivel_estoque=10,
            )
        )
    return ofertas


def _baixar_html_camuflado(url: str) -> str:
    """Resolve IPv4 pelo Windows e injeta-o no curl_cffi mantendo o TLS SNI original."""
    parsed = urlparse(url)
    host = parsed.hostname

    ip_alvo = None
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ip_alvo = infos[0][4][0]
            print(f"[DEBUG DNS] {host} resolvido pelo Windows para IPv4: {ip_alvo}")
    except Exception as e:
        print(f"[AVISO DNS] Falha no socket do Windows para {host}: {e}")

    if HAS_CFFI:
        curl_options = {}
        if ip_alvo:
            curl_options[CurlOpt.RESOLVE] = [f"{host}:443:{ip_alvo}"]

        with cffi_requests.Session(
            impersonate="chrome120",
            curl_options=curl_options
        ) as client:
            resp = client.get(
                url,
                timeout=12,
                headers={
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Referer": f"{parsed.scheme}://{host}/",
                }
            )
        print(f"[DEBUG HTTP] Status HTTP (curl_cffi): {resp.status_code} | Tamanho HTML: {len(resp.text)} bytes")
        return resp.text

    with httpx.Client(follow_redirects=True, timeout=12.0) as client:
        resp = client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"
        })
        print(f"[DEBUG HTTP] Status HTTP (httpx): {resp.status_code} | Tamanho HTML: {len(resp.text)} bytes")
        return resp.text


def _extrair_ofertas_do_html(html: str, termo: str, limite: int) -> List[OfertaWeb]:
    soup = BeautifulSoup(html, "html.parser")
    ofertas: List[OfertaWeb] = []

    cards = soup.select(
        "li.ui-search-layout__item, div.ui-search-result__wrapper, "
        "div.poly-card, div.andes-card"
    )
    print(f"[DEBUG ML] Cards HTML encontrados: {len(cards)}")

    for idx, card in enumerate(cards):
        if len(ofertas) >= limite:
            break

        link_el = (
            card.select_one("a.poly-component__title")
            or card.select_one("h2.ui-search-item__title a")
            or card.select_one("a.ui-search-link")
            or card.select_one("a[href*='mercadolivre.com.br']")
            or card.select_one("a[href*='produto.mercadolivre']")
        )
        if not link_el:
            continue

        titulo = link_el.get_text(strip=True)
        link_compra = link_el.get("href", "").split("#")[0]
        if not titulo or not link_compra:
            continue

        match_id = re.search(r"(MLB-?\d+)", link_compra)
        id_externo = match_id.group(1).replace("-", "") if match_id else f"MLB{idx+100}"

        preco_container = (
            card.select_one("div.poly-price__current")
            or card.select_one("div.ui-search-price__second-line")
            or card.select_one("span.andes-money-amount")
            or card
        )
        frac_el = preco_container.select_one("span.andes-money-amount__fraction")
        cents_el = preco_container.select_one("span.andes-money-amount__cents")
        if not frac_el:
            continue

        preco_str = frac_el.get_text(strip=True)
        if cents_el:
            preco_str += "," + cents_el.get_text(strip=True)
        preco = _limpar_preco_br(preco_str)
        if preco <= 0:
            continue

        texto_card = card.get_text(" ", strip=True).lower()
        frete_gratis = "frete grátis" in texto_card or "chegará grátis" in texto_card
        is_full = "full" in texto_card or bool(
            card.select_one("[class*='full'], svg[aria-label*='FULL']")
        )
        prazo_dias = 2 if is_full else (4 if frete_gratis else 6)

        cond_pgto = "À vista"
        if "sem juros" in texto_card:
            m_parc = re.search(r"(\d+x)\s*[^,]*sem juros", texto_card)
            cond_pgto = f"Até {m_parc.group(1)} sem juros" if m_parc else "Parcelado sem juros"

        vendedor_el = card.select_one(
            "span.poly-component__seller, p.ui-search-official-store-label"
        )
        nome_vendedor = (
            vendedor_el.get_text(strip=True).replace("Por ", "")
            if vendedor_el
            else "Vendedor Mercado Livre"
        )

        img_el = card.select_one("img")
        url_imagem = None
        if img_el:
            url_imagem = img_el.get("data-src") or img_el.get("src")
            if url_imagem and url_imagem.startswith("data:"):
                url_imagem = None

        ofertas.append(
            OfertaWeb(
                id_externo=id_externo,
                titulo=titulo,
                preco=preco,
                frete_gratis=frete_gratis,
                logistica_full=is_full,
                prazo_estimado_dias=prazo_dias,
                vendedor=f"ML • {nome_vendedor}",
                condicao_pagamento=cond_pgto,
                link_compra=link_compra,
                url_imagem=url_imagem,
                disponivel_estoque=15
            )
        )

    if not ofertas:
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "{}")
                items = data.get("itemListElement", []) if isinstance(data, dict) else []
                for idx, item in enumerate(items[:limite]):
                    prod = item.get("item", item)
                    preco = float(prod.get("offers", {}).get("price", 0) or 0)
                    if preco > 0:
                        ofertas.append(
                            OfertaWeb(
                                id_externo=f"MLBLD{idx+1}",
                                titulo=prod.get("name", termo.title()),
                                preco=preco,
                                frete_gratis=preco >= 79.0,
                                logistica_full=True,
                                prazo_estimado_dias=3,
                                vendedor="ML • Loja Oficial",
                                condicao_pagamento="À vista ou parcelado",
                                link_compra=prod.get(
                                    "url",
                                    f"https://lista.mercadolivre.com.br/{quote_plus(termo)}"
                                ),
                                url_imagem=prod.get("image"),
                                disponivel_estoque=10
                            )
                        )
            except Exception:
                pass

    return ofertas


def _extrair_ofertas_buscape(termo: str, limite: int) -> List[OfertaWeb]:
    url = f"https://www.buscape.com.br/search?q={quote_plus(termo)}"
    html = _baixar_html_camuflado(url)
    soup = BeautifulSoup(html, "html.parser")
    ofertas: List[OfertaWeb] = []
    vistos = set()

    def texto_de(valor, chaves):
        if isinstance(valor, dict):
            for chave in chaves:
                conteudo = valor.get(chave)
                if isinstance(conteudo, str) and conteudo.strip():
                    return conteudo.strip()
            for conteudo in valor.values():
                encontrado = texto_de(conteudo, chaves)
                if encontrado:
                    return encontrado
        elif isinstance(valor, list):
            for conteudo in valor:
                encontrado = texto_de(conteudo, chaves)
                if encontrado:
                    return encontrado
        return ""

    def preco_de(valor):
        if isinstance(valor, (int, float)):
            return float(valor)
        if isinstance(valor, str):
            limpo = re.sub(r"[^\d,.-]", "", valor)
            if not limpo:
                return 0.0
            if "," in limpo:
                limpo = limpo.replace(".", "").replace(",", ".")
            try:
                return float(limpo)
            except ValueError:
                return 0.0
        if isinstance(valor, dict):
            for chave in ("price", "currentPrice", "bestPrice", "value", "amount"):
                if chave in valor:
                    resultado = preco_de(valor[chave])
                    if resultado > 0:
                        return resultado
            for conteudo in valor.values():
                resultado = preco_de(conteudo)
                if resultado > 0:
                    return resultado
        elif isinstance(valor, list):
            for conteudo in valor:
                resultado = preco_de(conteudo)
                if resultado > 0:
                    return resultado
        return 0.0

    def mapear_produto(produto, indice):
        if not isinstance(produto, dict):
            return None

        titulo = texto_de(produto, ("title", "name", "productName", "displayName"))
        preco = 0.0
        for chave in ("price", "bestPrice", "currentPrice", "offers", "pricing"):
            if chave in produto:
                preco = preco_de(produto[chave])
                if preco > 0:
                    break
        if not titulo or preco <= 0:
            return None

        caminho = texto_de(produto, ("url", "href", "productUrl", "slug", "permalink"))
        link = urljoin("https://www.buscape.com.br/", caminho) if caminho else url
        imagem = texto_de(produto, ("imageUrl", "thumbnail", "src"))
        if not imagem:
            imagem = texto_de(
                produto.get("image") or produto.get("images") or {},
                ("url", "src", "original", "large")
            )

        loja = texto_de(produto, ("storeName", "sellerName", "merchantName"))
        if not loja:
            for chave in ("store", "seller", "merchant", "retailer"):
                valor_loja = produto.get(chave)
                loja = valor_loja.strip() if isinstance(valor_loja, str) else texto_de(
                    valor_loja,
                    ("name", "title", "label", "displayName")
                )
                if loja:
                    break
        loja = loja or "Loja no Buscapé"
        identificador = texto_de(produto, ("id", "productId", "sku")) or f"BUSCAPE{indice + 1}"

        return OfertaWeb(
            id_externo=identificador,
            titulo=titulo,
            preco=preco,
            frete_gratis=False,
            logistica_full=False,
            prazo_estimado_dias=0,
            vendedor=loja,
            loja_origem=loja,
            condicao_pagamento="Consulte as condições na loja",
            link_compra=link,
            url_imagem=urljoin("https://www.buscape.com.br/", imagem) if imagem else None,
            disponivel_estoque=1
        )

    def percorrer(valor):
        if isinstance(valor, dict):
            yield valor
            for filho in valor.values():
                yield from percorrer(filho)
        elif isinstance(valor, list):
            for filho in valor:
                yield from percorrer(filho)

    next_data = soup.select_one('script#__NEXT_DATA__[type="application/json"]')
    if next_data:
        try:
            dados = json.loads(next_data.string or next_data.get_text())
            page_props = dados.get("props", {}).get("pageProps", {})
            for item in percorrer(page_props):
                produto = mapear_produto(item, len(ofertas))
                if produto:
                    chave = (produto.id_externo, produto.link_compra)
                    if chave not in vistos:
                        vistos.add(chave)
                        ofertas.append(produto)
                        if len(ofertas) >= limite:
                            return ofertas
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            print(f"[AVISO BUSCAPE] Não foi possível ler __NEXT_DATA__: {e}")

    if len(ofertas) < limite:
        for card in soup.select('[data-testid="product-card"]'):
            if len(ofertas) >= limite:
                break

            link_el = card.select_one("a[href]")
            titulo_el = (
                card.select_one('[data-testid*="title"]')
                or card.select_one("h2")
                or card.select_one("h3")
                or link_el
            )
            preco_el = card.select_one('[data-testid*="price"]') or card.select_one(
                '[class*="price"]'
            )
            if not link_el or not titulo_el or not preco_el:
                continue

            titulo = titulo_el.get_text(" ", strip=True)
            preco = preco_de(preco_el.get_text(" ", strip=True))
            if not titulo or preco <= 0:
                continue

            href = link_el.get("href", "")
            imagem_el = card.select_one("img")
            imagem = (
                (imagem_el.get("src") or imagem_el.get("data-src"))
                if imagem_el
                else None
            )
            loja_el = card.select_one('[data-testid*="store"], [class*="store"]')
            loja = loja_el.get_text(" ", strip=True) if loja_el else "Loja no Buscapé"
            link = urljoin("https://www.buscape.com.br/", href)
            identificador = f"BUSCAPE{len(ofertas) + 1}"
            chave = (identificador, link)
            if chave in vistos:
                continue
            vistos.add(chave)
            ofertas.append(
                OfertaWeb(
                    id_externo=identificador,
                    titulo=titulo,
                    preco=preco,
                    frete_gratis=False,
                    logistica_full=False,
                    prazo_estimado_dias=0,
                    vendedor=loja,
                    loja_origem=loja,
                    condicao_pagamento="Consulte as condições na loja",
                    link_compra=link,
                    url_imagem=urljoin("https://www.buscape.com.br/", imagem) if imagem else None,
                    disponivel_estoque=1
                )
            )

    print(f"[DEBUG BUSCAPE] Ofertas extraídas: {len(ofertas)}")
    return ofertas[:limite]


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
        ("Mega Insumos Oficial", 1.09, True, True, 2, "Até 12x sem juros"),
        ("Fornecedora Direta SP", 1.14, False, False, 7, "À vista"),
    ]

    ofertas = []
    for idx, (vend, fator, fg, full, prazo, pgto) in enumerate(
        variacoes[:limite]
    ):
        preco_calc = round(base_preco * fator, 2)
        ofertas.append(
            OfertaWeb(
                id_externo=f"MLBSIM{1000+idx}",
                titulo=f"{termo_limpo} - Lote Comercial / Atacado ({idx+1})",
                preco=preco_calc,
                frete_gratis=fg,
                logistica_full=full,
                prazo_estimado_dias=prazo,
                vendedor=f"ML • {vend}",
                loja_origem="Mercado Livre",
                condicao_pagamento=pgto,
                link_compra=link_base,
                url_imagem="https://http2.mlstatic.com/frontend-assets/ml-web-navigation/ui-navigation/6.6.73/mercadolibre/logo_large_25years_v2.png",
                disponivel_estoque=50
            )
        )
    return ofertas


@app.get("/api/status")
async def status_api():
    return {
        "status": "online",
        "servico": "Mensura Buscador",
        "versao": "1.3.0",
        "fonte_busca": "Google Shopping (Serper)",
        "camuflagem_tls_ativa": HAS_CFFI
    }


@app.get("/api/ml/buscar", response_model=List[OfertaWeb])
async def rota_buscar_ml(
    q: str = Query(..., min_length=2, description="Produto para pesquisar"),
    limite: int = Query(10, ge=1, le=50),
    permitir_contingencia: bool = Query(
        True,
        description="Usa dados de contingência quando o Serper não está disponível"
    )
):
    ofertas: List[OfertaWeb] = []
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    serper_falhou = not api_key
    if api_key:
        try:
            ofertas = await buscar_google_shopping_serper(q, limite)
        except Exception as e:
            serper_falhou = True
            print(f"[ERRO SERPER SHOPPING] {e}")
    else:
        print("[ERRO SERPER SHOPPING] SERPER_API_KEY não está definida.")

    if serper_falhou and permitir_contingencia:
        print(f"[AVISO SERPER] Usando contingência para '{q}'.")
        ofertas = _gerar_fallback_simulacao_realista(q, limite)

    ofertas.sort(key=lambda x: (x.preco, not x.frete_gratis))
    return ofertas
