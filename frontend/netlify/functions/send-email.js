/* Envio direto de relatórios por e-mail (Netlify Function + Resend).
   Variáveis de ambiente no Netlify (Site settings > Environment variables):
   RESEND_API_KEY  chave da API do Resend (resend.com)
   EMAIL_FROM      remetente verificado no Resend, ex.: "Compras <compras@suaempresa.com.br>"
   APP_SECRET      (opcional, recomendado) senha de envio; o app a pede antes de enviar */
const resp=(s,o)=>({statusCode:s,headers:{'Content-Type':'application/json'},body:JSON.stringify(o)});
const EMAIL=/^[^\s@<>,;]+@[^\s@<>,;]+\.[^\s@<>,;]+$/;
exports.handler=async(event)=>{
  if(event.httpMethod!=='POST') return resp(405,{error:'Método não permitido.'});
  const key=process.env.RESEND_API_KEY, from=process.env.EMAIL_FROM;
  if(!key||!from) return resp(501,{error:'Envio direto não configurado: defina RESEND_API_KEY e EMAIL_FROM no Netlify.'});
  let b; try{ b=JSON.parse(event.body||'{}'); }catch(e){ return resp(400,{error:'Requisição inválida.'}); }
  if(process.env.APP_SECRET && b.secret!==process.env.APP_SECRET) return resp(401,{error:'Senha de envio incorreta.'});
  const to=Array.isArray(b.to)?b.to.map(String).map(s=>s.trim()):[];
  if(!to.length||to.length>10||!to.every(x=>EMAIL.test(x))) return resp(400,{error:'Destinatários inválidos (de 1 a 10 e-mails).'});
  const subject=String(b.subject||'').slice(0,200).replace(/[\r\n]+/g,' '), text=String(b.text||'').slice(0,5000);
  if(!subject) return resp(400,{error:'Informe o assunto.'});
  const att=[];
  if(b.content){ if(typeof b.content!=='string'||b.content.length>3.5*1024*1024) return resp(413,{error:'Anexo grande demais.'});
    att.push({filename:String(b.filename||'relatorio.html').replace(/[^\w.\- ]/g,'_').slice(0,100),content:b.content}); }
  try{
    const r=await fetch('https://api.resend.com/emails',{method:'POST',headers:{Authorization:'Bearer '+key,'Content-Type':'application/json'},body:JSON.stringify({from,to,subject,text,attachments:att})});
    const j=await r.json().catch(()=>({}));
    return r.ok?resp(200,{ok:true,id:j.id}):resp(502,{error:j.message||'O provedor de e-mail recusou o envio.'});
  }catch(e){ return resp(502,{error:'Não foi possível falar com o provedor de e-mail.'}); }
};
