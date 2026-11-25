// Utilidades compartilhadas pelos testes de interface.
const { expect } = require('@playwright/test');

const SCREENS = [
  'dashboard', 'search', 'suppliers', 'items', 'quotes', 'quote/new', 'compare', 'purchases',
  'stock', 'extrato', 'restock', 'panel', 'prices', 'history', 'annual', 'reports', 'email', 'data',
];

// Ofertas falsas devolvidas pelo backend simulado. Uma delas traz HTML malicioso no título
// para provar que a interface escapa tudo o que vem da internet.
const OFFERS = [
  { id_externo: 'a1', titulo: 'Soja em grão 50 kg', preco: 212.5, frete_gratis: true, logistica_full: true, prazo_estimado_dias: 2, vendedor: 'Loja A', loja_origem: 'Loja A', site_dominio: 'loja-a.com.br', condicao_pagamento: 'Pix', link_compra: 'https://loja-a.com.br/p/1', url_imagem: 'data:image/gif;base64,R0lGODlhAQABAAAAACw=', disponivel_estoque: 10 },
  { id_externo: 'b2', titulo: '<img src=x onerror="window.__xss=1">Soja XSS', preco: 199.9, frete_gratis: false, logistica_full: false, prazo_estimado_dias: 5, vendedor: 'Loja B', loja_origem: 'Loja B', site_dominio: 'loja-b.com.br', condicao_pagamento: 'Boleto', link_compra: 'javascript:alert(1)', url_imagem: null, disponivel_estoque: 10 },
  { id_externo: 'c3', titulo: 'Soja tipo 1 saco', preco: 230, frete_gratis: true, logistica_full: false, prazo_estimado_dias: 3, vendedor: 'Loja C', loja_origem: 'Loja C', site_dominio: 'loja-c.com.br', condicao_pagamento: 'Cartão', link_compra: 'https://loja-c.com.br/p/3', url_imagem: null, disponivel_estoque: 10 },
];

/** Abre o app registrando erros de JavaScript e de console para o teste conferir no final. */
async function openApp(page, hash = 'dashboard', { api = 'ok', delayMs = 0 } = {}) {
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) errors.push('console: ' + m.text()); });
  // Nunca deixa o teste depender de serviços externos.
  await page.route('https://api.mercadolibre.com/**', r => r.abort());
  await page.route('**/api/ml/buscar**', async r => {
    if (delayMs) await new Promise(res => setTimeout(res, delayMs));
    if (api === 'down') return r.fulfill({ status: 503, body: 'indisponível' });
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OFFERS) });
  });
  await page.goto('/#' + hash);
  await expect(page.locator('#view')).not.toBeEmpty();
  return errors;
}

/** Fecha o diálogo de "pedidos chegaram?" que pode abrir sozinho com os dados de exemplo. */
async function dismissDialog(page) {
  const dlg = page.locator('#dlg[open]');
  if (await dlg.count()) await page.locator('#dlgCancel').click();
}

module.exports = { SCREENS, OFFERS, openApp, dismissDialog };
