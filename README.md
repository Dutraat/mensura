# Mensura — Busca de Preços Online e Controle de Estoque

Aplicação web (Netlify + FastAPI no Render) para buscar ofertas reais na internet, comparar preços com histórico/melhor época e registrar compras direto no estoque.

## 1. Publicar o Backend em HTTPS (Render)
1. Acesse [render.com](https://render.com) → **New +** → **Blueprint** e conecte o repositório `Dutraat/mensura`.
2. O `render.yaml` aponta o serviço para `master`. Após sincronizar o Blueprint, confirme em **Settings → Build & Deploy** que a branch de produção é `master`, para que pushes na branch de desenvolvimento não publiquem alterações.
3. Em **Environment Variables**, cadastre sua `SERPER_API_KEY` (nunca coloque a chave no código).
4. O serviço está em `https://mensura-api-u9s5.onrender.com`; teste `https://mensura-api-u9s5.onrender.com/api/status`.
5. O `render.yaml` configura o cache de buscas com `MENSURA_CACHE_TTL=86400` (24 horas).

## 2. Publicar o Frontend (Netlify)
1. No Netlify, conecte o repositório `Dutraat/mensura` com **Base directory** = `frontend` e **Publish directory** = `.`.
2. (Opcional, para envio de relatórios por e-mail) Em **Site configuration → Environment variables**, cadastre `RESEND_API_KEY`, `EMAIL_FROM` e `APP_SECRET`.
3. O arquivo `frontend/netlify.toml` redireciona automaticamente `/api/*` para o Render em HTTPS — sem erro de CORS nem Mixed Content.
4. O site já inclui `manifest.json` (PWA): no Chrome ou Edge, clique no ícone de instalar na barra de endereço para usar o Mensura como aplicativo no computador ou celular.

## 3. Rodar localmente no Windows
1. Crie um arquivo `.env` na raiz (baseado em `.env.example`) com `SERPER_API_KEY=sua_chave`.
2. Dê dois cliques em `iniciar_windows.bat`. Para iniciar manualmente, use `python -m pip install -r backend/requirements.txt` e `python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`.

## 4. Cache e extração JSON-LD
- `GET /api/ml/buscar?q=...` armazena em SQLite, por 24 horas, somente respostas bem-sucedidas da Serper; resultados de contingência não são armazenados.
- `GET /api/cache/status` informa entradas ativas, hits, misses e TTL.
- `GET /api/extrair-url?url=...` extrai ofertas de JSON-LD. Por segurança, aceita somente URLs públicas, valida cada redirecionamento e limita o HTML a 5 MiB.
- O banco local fica em `backend/.mensura_cache.db` e é ignorado pelo Git. O cache de instâncias Render é efêmero.
