# Mensura — Busca de Preços Online e Controle de Estoque

Aplicação web (Netlify + FastAPI no Render) para buscar ofertas reais na internet, comparar preços com histórico/melhor época e registrar compras direto no estoque.

## 1. Como aplicar esta atualização no seu repositório (Windows)
1. Extraia o conteúdo deste pacote na raiz da sua pasta local do repositório `mensura` (substituindo os arquivos existentes).
2. Dê dois cliques em `aplicar_atualizacao_windows.bat`. Ele vai:
   - Remover `iniciar_linux.sh` e qualquer serviço Linux;
   - Corrigir o `CORSMiddleware` e a função `_limpar_preco_br` (suporte a preços BR e US) no seu `backend/main.py` sem mexer na sua lógica da Serper;
   - Validar a sintaxe do Python automaticamente.
3. Suba as alterações para o GitHub (`git status`, `git add .`, `git commit -m "Deploy web Render + Netlify"`, `git push`).

## 2. Publicar o Backend em HTTPS (Render)
1. Acesse [render.com](https://render.com) → **New +** → **Blueprint** e conecte o repositório `Dutraat/mensura`.
2. O Render vai ler o arquivo `render.yaml` automaticamente.
3. Em **Environment Variables**, cadastre sua `SERPER_API_KEY` (nunca coloque a chave no código).
4. O serviço deste deploy foi criado em `https://mensura-api-u9s5.onrender.com`; teste `https://mensura-api-u9s5.onrender.com/api/status`.
5. Se você recriar o serviço e receber outra URL, atualize o domínio em `frontend/netlify.toml` e faça novo push.

## 3. Publicar o Frontend (Netlify)
1. No Netlify, conecte o repositório `Dutraat/mensura` com **Base directory** = `frontend` e **Publish directory** = `.`.
2. (Opcional, para envio de relatórios por e-mail) Em **Site configuration → Environment variables**, cadastre `RESEND_API_KEY`, `EMAIL_FROM` e `APP_SECRET`.
3. O arquivo `frontend/netlify.toml` redireciona automaticamente `/api/*` para o Render em HTTPS — sem erro de CORS nem Mixed Content.
4. O site já inclui `manifest.json` (PWA): no Chrome ou Edge, clique no ícone de instalar na barra de endereço para usar o Mensura como aplicativo no computador ou celular.

## 4. Rodar localmente no Windows
1. Crie um arquivo `.env` na raiz (baseado em `.env.example`) com `SERPER_API_KEY=sua_chave`.
2. Dê dois cliques em `iniciar_windows.bat`.
