# Mensura

Aplicação Mensura com interface web e API FastAPI servidas juntas pelo mesmo
processo. A interface em `frontend/index.html` não precisa de uma etapa de
compilação separada; o backend a publica em `/` e expõe a API em `/api`.

## Executar no Windows

Requer Python 3.10 ou superior. Na raiz do repositório, execute:

```powershell
.\iniciar_windows.bat
```

Ou configure manualmente:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item .env.example .env
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Abra <http://127.0.0.1:8000/>. A documentação interativa da API fica em
<http://127.0.0.1:8000/docs>.

## Executar no Linux

Na raiz do repositório, execute `bash iniciar_linux.sh`. O script cria `.venv`,
instala `backend/requirements.txt` e inicia a aplicação em
<http://127.0.0.1:8000/>.

## Busca de preços

Configure `SERPER_API_KEY` no arquivo `.env` para usar o Google Shopping via
Serper. Sem a chave, a API usa os resultados de contingência já implementados.
O `.env` está excluído do Git; nunca coloque chaves no frontend.

Rotas principais:

- `GET /api/status`
- `GET /api/ml/buscar?q=termo&limite=10&permitir_contingencia=true`

O frontend usa automaticamente a API na mesma origem. Também é possível
configurar um endereço de API diferente na interface.

## E-mail e Netlify

O envio direto de relatórios depende da função Netlify em
`frontend/netlify/functions/send-email.js`. Para esse recurso, publique a pasta
`frontend/` no Netlify e configure `RESEND_API_KEY`, `EMAIL_FROM` e,
opcionalmente, `APP_SECRET` como variáveis de ambiente do Netlify. Essas
variáveis não são necessárias para executar a aplicação localmente.
