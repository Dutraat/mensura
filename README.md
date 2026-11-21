# Mensura

Repositório principal do Mensura. O backend de busca está em `backend/`; o
frontend poderá ser adicionado em `frontend/` quando estiver pronto.

## Backend

Requisitos: Python 3.14 ou compatível com as dependências listadas.

No PowerShell, na raiz do repositório:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
```

Edite `.env` e configure `SERPER_API_KEY` com sua chave. Esse arquivo é
ignorado pelo Git; não publique chaves ou outros segredos.

Inicie a API:

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Rotas principais:

- `GET /api/status`
- `GET /api/ml/buscar?q=termo&limite=10&permitir_contingencia=true`
