// Etapa 2: skeleton, atualização sem esperar o servidor e lazy loading.
const { test, expect } = require('@playwright/test');
const { OFFERS, openApp, dismissDialog } = require('./helpers');

const offersFor = (q, bump = 0) => OFFERS.map(o => ({ ...o, titulo: `${q} — ${o.titulo}`, preco: o.preco + bump }));

async function search(page, q) {
  await page.fill('#wsQ', q);
  await page.press('#wsQ', 'Enter');
}

test.describe('Skeleton de carregamento', () => {
  test('o HTML já chega com skeleton, e ele some quando o app desenha', async ({ page, request }) => {
    const html = await (await request.get('/')).text();
    expect(html).toContain('class="sk-boot"');
    await openApp(page, 'dashboard');
    await expect(page.locator('.sk-boot')).toHaveCount(0);
  });

  test('busca lenta mostra cartões-skeleton e depois as ofertas', async ({ page }) => {
    await openApp(page, 'search', { delayMs: 900 });
    await dismissDialog(page);
    await search(page, 'Soja');
    await expect(page.locator('.sk-ocard')).toHaveCount(6);
    await expect(page.locator('#wsResults')).toHaveAttribute('aria-busy', 'true');
    await expect(page.locator('.web-ocard:not(.sk-ocard)')).toHaveCount(3);
    await expect(page.locator('.sk-ocard')).toHaveCount(0);
  });

  for (const s of ['history', 'annual']) {
    test(`#${s} abre com skeleton e desenha o conteúdo logo depois`, async ({ page }) => {
      const errors = await openApp(page, s);
      await expect(page.locator(s === 'history' ? '#hview table' : '#aview .card').first()).toBeVisible();
      await expect(page.locator(`${s === 'history' ? '#hview' : '#aview'} .sk`)).toHaveCount(0);
      expect(errors).toEqual([]);
    });
  }
});

test.describe('Atualizar a tela sem esperar o servidor', () => {
  test('busca repetida aparece na hora e se atualiza em segundo plano', async ({ page }) => {
    let bump = 0, delay = 0;
    await openApp(page, 'search');
    await page.unroute('**/api/ml/buscar**');
    await page.route('**/api/ml/buscar**', async r => {
      await new Promise(res => setTimeout(res, delay));
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(offersFor('Soja', bump)) });
    });
    await dismissDialog(page);
    await search(page, 'Soja');
    await expect(page.locator('.web-ocard-unit').first()).toHaveText(/199,90/);

    // Servidor ficou lento e os preços mudaram.
    bump = 10; delay = 1500;
    await page.evaluate(() => { location.hash = '#dashboard'; });
    await page.evaluate(() => { location.hash = '#search'; });
    await search(page, 'Soja');
    // Sem esperar: o resultado salvo aparece imediatamente, com o aviso de atualização.
    await expect(page.locator('.web-ocard-unit').first()).toHaveText(/199,90/, { timeout: 400 });
    await expect(page.getByText('Atualizando preços…')).toBeVisible();
    // Quando o servidor responde, os cartões trocam sozinhos.
    await expect(page.locator('.web-ocard-unit').first()).toHaveText(/209,90/, { timeout: 4000 });
    await expect(page.getByText('Atualizando preços…')).toHaveCount(0);
  });

  test('servidor fora do ar depois: mantém o último resultado e avisa', async ({ page }) => {
    let down = false;
    await openApp(page, 'search');
    await page.unroute('**/api/ml/buscar**');
    await page.route('**/api/ml/buscar**', r => down
      ? r.fulfill({ status: 503, body: '' })
      : r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(OFFERS) }));
    await dismissDialog(page);
    await search(page, 'Soja');
    await expect(page.locator('.web-ocard')).toHaveCount(3);
    down = true;
    await search(page, 'Soja');
    await expect(page.locator('#wsResults')).toContainText('Não foi possível atualizar agora');
    await expect(page.locator('.web-ocard')).toHaveCount(3);
  });

  test('resposta atrasada de uma busca antiga não sobrescreve a busca nova', async ({ page }) => {
    await openApp(page, 'search');
    await page.unroute('**/api/ml/buscar**');
    await page.route('**/api/ml/buscar**', async r => {
      const q = new URL(r.request().url()).searchParams.get('q');
      if (q === 'Lenta') await new Promise(res => setTimeout(res, 1500));
      r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(offersFor(q)) });
    });
    await dismissDialog(page);
    await search(page, 'Lenta');
    await search(page, 'Rapida');
    await expect(page.locator('.web-ocard-title').first()).toContainText('Rapida');
    await page.waitForTimeout(1800);
    await expect(page.locator('.web-ocard-title').first()).toContainText('Rapida');
  });

  test('o app acorda o servidor logo depois de carregar', async ({ page }) => {
    const hit = page.waitForRequest(r => r.url().endsWith('/api/status'), { timeout: 8000 });
    await openApp(page, 'dashboard');
    await hit;
  });
});

test.describe('Lazy loading e re-render', () => {
  test('imagens das ofertas carregam sob demanda', async ({ page }) => {
    await openApp(page, 'search');
    await dismissDialog(page);
    await search(page, 'Soja');
    const img = page.locator('.web-ocard img').first();
    await expect(img).toHaveAttribute('loading', 'lazy');
    await expect(img).toHaveAttribute('decoding', 'async');
  });

  test('digitar na pesquisa do histórico redesenha só uma vez', async ({ page }) => {
    await openApp(page, 'history');
    await expect(page.locator('#hview table')).toBeVisible();
    await page.evaluate(() => {
      window.__hdraws = 0;
      new MutationObserver(() => window.__hdraws++).observe(document.getElementById('hview'), { childList: true });
    });
    await page.locator('#hq').pressSequentially('soja', { delay: 30 });
    await page.waitForTimeout(400);
    expect(await page.evaluate(() => window.__hdraws)).toBe(1);
  });
});
