# Frontend Mensura

O aplicativo é servido pelo backend FastAPI em `http://127.0.0.1:8000/` quando
executado a partir da raiz do repositório. Como o frontend é um HTML autocontido,
não há etapa de build ou dependências JavaScript para instalar.

Para publicar a interface separadamente no Netlify, use esta pasta como diretório
base do deploy. O arquivo `netlify.toml` define a publicação e a função de envio
de e-mail. Configure as credenciais do Resend somente como variáveis de ambiente
no Netlify; não as adicione aos arquivos do frontend.
