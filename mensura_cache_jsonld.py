"""
Modulo de Cache 24h (SQLite + memoria) e Extrator JSON-LD (schema.org/Product) para o Mensura.
- Reduz drasticamente o consumo de creditos da Serper armazenando buscas repetidas por 24h.
- Permite extrair precos reais de paginas publicas de lojas via JSON-LD sem custo de API.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, quote_plus, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

CACHE_TTL_SEGUNDOS = int(os.getenv("MENSURA_CACHE_TTL", "86400"))  # 24 horas


def limpar_preco_universal(valor: Any) -> float:
    """Converte precos em formato BR (R$ 1.234,56) ou US ($ 1,234.56) para float."""
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


class CacheBuscas:
    """Cache persistente em SQLite (com fallback em /tmp para Render) com TTL configuravel."""

    def __init__(self, ttl_segundos: int = CACHE_TTL_SEGUNDOS, db_path: Path | None = None):
        self.ttl = max(60, int(ttl_segundos))
        self.hits = 0
        self.misses = 0
        if db_path is None:
            base = Path(tempfile.gettempdir()) if os.getenv("RENDER") else Path(__file__).resolve().parent
            db_path = base / ".mensura_cache.db"
        self.db_path = Path(db_path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path), timeout=5.0)

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_buscas (
                    chave TEXT PRIMARY KEY,
                    termo TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    criado_em REAL NOT NULL
                )
                """
            )
            con.commit()

    @staticmethod
    def _normalizar_chave(termo: str, limite: str, regiao: str = "") -> str:
        t = re.sub(r"\s+", " ", (termo or "").strip().lower())
        r = re.sub(r"\s+", " ", (regiao or "").strip().lower())
        return hashlib.sha256(f"v3|{t}|{limite}|{r}".encode("utf-8")).hexdigest()

    def obter(self, termo: str, limite: str = "10", regiao: str = "") -> Any | None:
        chave = self._normalizar_chave(termo, limite, regiao)
        agora = time.time()
        with self._conn() as con:
            row = con.execute(
                "SELECT payload, criado_em FROM cache_buscas WHERE chave = ?", (chave,)
            ).fetchone()
            if not row:
                self.misses += 1
                return None
            payload_str, criado_em = row
            if (agora - float(criado_em)) > self.ttl:
                con.execute("DELETE FROM cache_buscas WHERE chave = ?", (chave,))
                con.commit()
                self.misses += 1
                return None
        self.hits += 1
        try:
            return json.loads(payload_str)
        except json.JSONDecodeError:
            return None

    def salvar(self, termo: str, limite: str, dados: Any, regiao: str = "") -> None:
        chave = self._normalizar_chave(termo, limite, regiao)
        payload_str = json.dumps(dados, ensure_ascii=False)
        with self._conn() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO cache_buscas (chave, termo, payload, criado_em)
                VALUES (?, ?, ?, ?)
                """,
                (chave, (termo or "").strip().lower(), payload_str, time.time()),
            )
            con.commit()

    def limpar(self) -> int:
        with self._conn() as con:
            cur = con.execute("DELETE FROM cache_buscas")
            con.commit()
            return int(cur.rowcount or 0)

    def status(self) -> dict[str, Any]:
        agora = time.time()
        with self._conn() as con:
            con.execute("DELETE FROM cache_buscas WHERE (? - criado_em) > ?", (agora, self.ttl))
            con.commit()
            total = con.execute("SELECT COUNT(*) FROM cache_buscas").fetchone()[0]
        return {
            "entradas_ativas": int(total),
            "hits_economizados": self.hits,
            "misses": self.misses,
            "ttl_horas": round(self.ttl / 3600, 2),
        }


def _iter_objetos_jsonld(obj: Any):
    if isinstance(obj, list):
        for item in obj:
            yield from _iter_objetos_jsonld(item)
    elif isinstance(obj, dict):
        yield obj
        if "@graph" in obj:
            yield from _iter_objetos_jsonld(obj["@graph"])
        if "itemListElement" in obj:
            yield from _iter_objetos_jsonld(obj["itemListElement"])
        if "item" in obj and isinstance(obj["item"], (dict, list)):
            yield from _iter_objetos_jsonld(obj["item"])


def _tipo_eh_produto(node: dict[str, Any]) -> bool:
    t = node.get("@type")
    if isinstance(t, list):
        return any(str(x).lower() in ("product", "productgroup") for x in t)
    return str(t or "").lower() in ("product", "productgroup")


def _extrair_imagem(img: Any) -> str | None:
    if isinstance(img, str) and img.startswith("http"):
        return img
    if isinstance(img, list):
        for x in img:
            res = _extrair_imagem(x)
            if res:
                return res
    if isinstance(img, dict):
        for k in ("url", "contentUrl"):
            if isinstance(img.get(k), str) and img[k].startswith("http"):
                return img[k]
    return None


def extrair_ofertas_jsonld_de_html(html: str, url_origem: str) -> list[dict[str, Any]]:
    """Extrai ofertas padronizadas (schema OfertaWeb) dos blocos JSON-LD de uma pagina HTML."""
    soup = BeautifulSoup(html, "html.parser")
    dominio = (urlparse(url_origem).netloc or "Loja Online").replace("www.", "")
    ofertas: list[dict[str, Any]] = []
    vistos: set[tuple[str, float]] = set()

    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = (script.string or script.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for node in _iter_objetos_jsonld(data):
            if not _tipo_eh_produto(node):
                continue
            titulo = str(node.get("name") or "").strip()
            if not titulo:
                continue
            url_img = _extrair_imagem(node.get("image"))
            offers_raw = node.get("offers")
            if isinstance(offers_raw, dict):
                offers_list = [offers_raw]
            elif isinstance(offers_raw, list):
                offers_list = [o for o in offers_raw if isinstance(o, dict)]
            else:
                offers_list = []

            for idx, off in enumerate(offers_list):
                preco = limpar_preco_universal(
                    off.get("price") or off.get("lowPrice") or off.get("highPrice")
                )
                if preco <= 0:
                    continue
                chave_dedup = (titulo.lower(), preco)
                if chave_dedup in vistos:
                    continue
                vistos.add(chave_dedup)

                seller = off.get("seller")
                vendedor = (
                    seller.get("name")
                    if isinstance(seller, dict) and seller.get("name")
                    else dominio
                )
                avail = str(off.get("availability") or "").lower()
                disponivel = "outofstock" not in avail
                link = str(off.get("url") or node.get("url") or url_origem).strip()
                ofertas.append(
                    {
                        "id_externo": f"jsonld_{hashlib.md5(f'{titulo}|{preco}|{idx}'.encode()).hexdigest()[:10]}",
                        "titulo": titulo,
                        "preco": preco,
                        "frete_gratis": False,
                        "logistica_full": False,
                        "prazo_estimado_dias": 4,
                        "vendedor": str(vendedor),
                        "loja_origem": dominio,
                        "condicao_pagamento": "Online / Pix",
                        "link_compra": link,
                        "url_imagem": url_img,
                        "disponivel_estoque": disponivel,
                    }
                )

    ofertas.sort(key=lambda x: x["preco"])
    return ofertas


async def extrair_ofertas_jsonld(url: str, timeout: float = 10.0) -> list[dict[str, Any]]:
    """Baixa uma pagina publica de produto/loja e extrai ofertas via JSON-LD sem custo de API."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Informe uma URL valida com http:// ou https://.")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return extrair_ofertas_jsonld_de_html(resp.text, str(resp.url))




LOJAS_DIRETAS_BR = [
    (("mercado livre", "mercadolivre", "ml"), lambda q: f"https://lista.mercadolivre.com.br/{quote(q.replace(' ', '-'))}"),
    (("amazon",), lambda q: f"https://www.amazon.com.br/s?k={quote_plus(q)}"),
    (("magalu", "magazine luiza", "magazine"), lambda q: f"https://www.magazineluiza.com.br/busca/{quote(q)}/"),
    (("shopee",), lambda q: f"https://shopee.com.br/search?keyword={quote_plus(q)}"),
    (("americanas",), lambda q: f"https://www.americanas.com.br/busca/{quote(q)}"),
    (("casas bahia", "casasbahia"), lambda q: f"https://www.casasbahia.com.br/{quote(q)}/b"),
    (("carrefour",), lambda q: f"https://www.carrefour.com.br/busca/{quote(q)}"),
    (("kalunga",), lambda q: f"https://www.kalunga.com.br/busca/1?q={quote_plus(q)}"),
    (("leroy", "leroy merlin"), lambda q: f"https://www.leroymerlin.com.br/search?term={quote_plus(q)}"),
    (("atacadao", "atacadão"), lambda q: f"https://www.atacadao.com.br/s?q={quote_plus(q)}"),
    (("assai", "assaí"), lambda q: f"https://www.assai.com.br/busca?q={quote_plus(q)}"),
    (("extra",), lambda q: f"https://www.extra.com.br/{quote(q)}/b"),
    (("ponto", "pontofrio"), lambda q: f"https://www.pontofrio.com.br/{quote(q)}/b"),
    (("kabum",), lambda q: f"https://www.kabum.com.br/busca/{quote(q.replace(' ', '-'))}"),
]


def _eh_url_google(url: str) -> bool:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return False
    return host == "google.com" or host.endswith(".google.com") or host.endswith(".google.com.br")


def resolver_link_direto(url: str, titulo: str = "", loja: str = "") -> str:
    """Remove redirecionamentos do Google e devolve o link direto da loja sempre que possivel."""
    u = (url or "").strip()
    if u:
        for _ in range(3):
            if not _eh_url_google(u):
                return u
            parsed = urlparse(u)
            qs = parse_qs(parsed.query)
            extraido = None
            for param in ("url", "adurl", "q", "u", "dest", "continue"):
                vals = qs.get(param)
                if vals and vals[0].startswith(("http://", "https://")):
                    extraido = unquote(vals[0]).strip()
                    break
            if extraido and extraido != u:
                u = extraido
                continue
            break

    if u and not _eh_url_google(u):
        return u

    # Fallback direto para a loja mencionada quando o Google Shopping so entrega link interno do Google
    termo = (titulo or "").strip()
    loja_l = (loja or "").lower()
    for chaves, builder in LOJAS_DIRETAS_BR:
        if any(k in loja_l for k in chaves):
            return builder(termo or loja)

    # Se loja for um dominio (ex: "atacadoxyz.com.br"), monta URL direta
    m_dom = re.search(r"([a-z0-9-]+\.(?:com\.br|com|net\.br|org\.br))", loja_l)
    if m_dom:
        return f"https://{m_dom.group(1)}"

    # Ultimo recurso: busca direta no Mercado Livre em vez de cair no Google
    if termo:
        return f"https://lista.mercadolivre.com.br/{quote(termo.replace(' ', '-'))}"
    return u


def normalizar_e_ordenar_payload_busca(data: Any) -> Any:
    """Corrige links de compra (sem redirecionamento Google) e ordena ofertas por menor preco."""
    def _proc_lista(items: list[Any]) -> list[Any]:
        validos = []
        for item in items:
            if not isinstance(item, dict):
                continue
            preco_num = limpar_preco_universal(item.get("preco"))
            if preco_num > 0:
                item["preco"] = preco_num
            loja_txt = f"{item.get('loja_origem') or ''} {item.get('vendedor') or ''} {item.get('loja') or ''}"
            link_final = resolver_link_direto(
                str(item.get("link_compra") or ""),
                str(item.get("titulo") or ""),
                loja_txt,
            )
            item["link_compra"] = link_final
            try:
                host = (urlparse(link_final).netloc or "").lower().replace("www.", "")
                if host.startswith("lista."):
                    host = host[6:]
                elif host.startswith("produto."):
                    host = host[8:]
                item["site_dominio"] = host or str(item.get("loja_origem") or "Site oficial")
            except Exception:
                item["site_dominio"] = str(item.get("loja_origem") or "Site oficial")
            validos.append(item)
        validos.sort(key=lambda x: float(x.get("preco") or 999999999))
        return validos

    if isinstance(data, list):
        return _proc_lista(data)
    if isinstance(data, dict):
        for k in ("ofertas", "resultados"):
            if isinstance(data.get(k), list):
                data[k] = _proc_lista(data[k])
        return data
    return data


def registrar_rotas_e_cache(app: FastAPI) -> CacheBuscas:
    """Registra middleware de cache 24h em /api/ml/buscar e endpoints utilitarios no FastAPI."""
    cache = CacheBuscas()

    @app.middleware("http")
    async def mensura_cache_middleware(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/api/ml/buscar":
            termo = (request.query_params.get("q") or "").strip()
            limite = request.query_params.get("limite", "10")
            regiao = (request.query_params.get("regiao") or "").strip()
            ignorar = (request.query_params.get("sem_cache") or "").lower() in ("1", "true", "sim")
            if termo and not ignorar:
                cached = cache.obter(termo, limite, regiao)
                if cached is not None:
                    return JSONResponse(
                        content=cached,
                        headers={"X-Mensura-Cache": "HIT"},
                    )
            response = await call_next(request)
            if termo and response.status_code == 200:
                chunks = [chunk async for chunk in response.body_iterator]
                body = b"".join(chunks)
                try:
                    data = json.loads(body.decode("utf-8"))
                    data = normalizar_e_ordenar_payload_busca(data)
                    tem_dados = (isinstance(data, list) and len(data) > 0) or (
                        isinstance(data, dict) and bool(data.get("ofertas") or data.get("resultados"))
                    )
                    if tem_dados:
                        cache.salvar(termo, limite, data, regiao)
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                except Exception:
                    pass
                headers = dict(response.headers)
                headers["X-Mensura-Cache"] = "MISS"
                headers.pop("content-length", None)
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=headers,
                    media_type=response.media_type or "application/json",
                )
            return response
        return await call_next(request)

    @app.get("/api/cache/status")
    def status_cache():
        return {"ok": True, **cache.status()}

    @app.delete("/api/cache/limpar")
    def limpar_cache():
        removidos = cache.limpar()
        return {"ok": True, "entradas_removidas": removidos}

    @app.get("/api/extrair-url")
    async def extrair_url_jsonld(url: str = Query(..., description="URL publica de produto ou loja com JSON-LD")):
        try:
            ofertas = await extrair_ofertas_jsonld(url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Nao foi possivel acessar a URL: {exc}") from exc
        return {
            "fonte": "json-ld",
            "url": url,
            "total": len(ofertas),
            "ofertas": ofertas,
        }

    return cache
