// Etapa 3: GSAP + ScrollTrigger carregados depois da página, sem esconder conteúdo nem quebrar o app.
const { test, expect } = require('@playwright/test');
const { openApp, dismissDialog } = require('./helpers');

const GSAP = /cdnjs\.cloudflare\.com\/ajax\/libs\/gsap\//;

async function waitMotion(page) {
  await page.waitForFunction(() => window.gsap && window.ScrollTrigger, null, { timeout: 15000 });
}

/** Rola até o fim do conteúdo, aos poucos, e espera as animações terminarem. */
async function scrollAll(page) {
  await page.evaluate(async () => {
    const m = document.querySelector('main');
    const sc = getComputedStyle(m).overflowY === 'auto' && m.scrollHeight > m.clientHeight ? m : document.scrollingElement;
    for (let y = 0; y <= sc.scrollHeight; y += 300) { sc.scrollTop = y; await new Promise(r => setTimeout(r, 60)); }
  });
  await page.waitForTimeout(900);
}

const hiddenCards = page => page.evaluate(() =>
  [...document.querySelectorAll('#view .card, #view .web-ocard, #view .kpi, #view .atile')]
    .filter(el => el.offsetParent && parseFloat(getComputedStyle(el).opacity) < 0.99).length);

test.describe('GSAP e ScrollTrigger', () => {
  test('scripts de terceiros só são pedidos depois do carregamento da página', async ({ page }) => {
    let loadedAt = 0, gsapAt = 0;
    page.on('load', () => { loadedAt = Date.now(); });
    page.on('request', r => { if (GSAP.test(r.url()) && !gsapAt) gsapAt = Date.now(); });
    await openApp(page, 'dashboard');
    await waitMotion(page);
    expect(loadedAt).toBeGreaterThan(0);
    expect(gsapAt).toBeGreaterThanOrEqual(loadedAt);
    // E com integridade (SRI) e sem bloquear o parser.
    const tags = await page.$$eval('script[src*="gsap"]', s => s.map(x => ({ async: x.async, sri: x.integrity })));
    expect(tags.length).toBe(2);
    tags.forEach(t => { expect(t.async).toBe(true); expect(t.sri).toMatch(/^sha384-/); });
  });

  for (const s of ['dashboard', 'restock', 'panel', 'history']) {
    test(`#${s}: depois de rolar, nenhum cartão fica invisível`, async ({ page }) => {
      const errors = await openApp(page, s);
      await waitMotion(page);
      await dismissDialog(page);
      // Navega para a tela de novo para disparar as animações de entrada com o GSAP já carregado.
      await page.evaluate(() => { location.hash = '#data'; });
      await page.evaluate(h => { location.hash = '#' + h; }, s);
      await scrollAll(page);
      expect(await hiddenCards(page)).toBe(0);
      expect(errors, errors.join('\n')).toEqual([]);
    });
  }

  for (const s of ['dashboard', 'restock', 'stock']) {
    test(`#${s}: rolar nunca esconde conteúdo (nem por um instante)`, async ({ page }) => {
      await openApp(page, s);
      await waitMotion(page);
      await dismissDialog(page);
      await page.evaluate(() => { location.hash = '#data'; });
      await page.evaluate(h => { location.hash = '#' + h; }, s);
      // Mede logo após a troca de tela e durante a rolagem, sem esperar animações terminarem.
      const worst = await page.evaluate(async () => {
        const m = document.querySelector('main');
        const sc = getComputedStyle(m).overflowY === 'auto' && m.scrollHeight > m.clientHeight ? m : document.scrollingElement;
        let min = 1;
        const probe = () => document.querySelectorAll('#view .card, #view .kpi, #view .atile, #view .attn2').forEach(el => {
          if (el.offsetParent) min = Math.min(min, parseFloat(getComputedStyle(el).opacity));
        });
        for (let y = 0; y <= sc.scrollHeight; y += 200) { sc.scrollTop = y; await new Promise(r => requestAnimationFrame(r)); probe(); }
        return min;
      });
      expect(worst).toBe(1);
    });
  }

  test('KPIs mostram o valor real (sem contagem animada)', async ({ page, browser }) => {
    const ref = await browser.newContext({ reducedMotion: 'reduce' });
    const rp = await ref.newPage();
    await openApp(rp, 'dashboard');
    const expected = await rp.locator('.kq .v').allTextContents();
    await ref.close();
    expect(expected.length).toBeGreaterThan(0);
    expect(expected.join(' ')).toMatch(/R\$\s?[\d.]+,\d{2}/);

    await openApp(page, 'dashboard');
    await waitMotion(page);
    await page.evaluate(() => { location.hash = '#data'; });
    await page.evaluate(() => { location.hash = '#dashboard'; });
    await page.waitForTimeout(1300);
    expect(await page.locator('.kq .v').allTextContents()).toEqual(expected);
  });

  test('ofertas animam ao chegar, mas não a cada tecla na quantidade', async ({ page }) => {
    await openApp(page, 'search');
    await waitMotion(page);
    await dismissDialog(page);
    await page.fill('#wsQ', 'Soja');
    await page.press('#wsQ', 'Enter');
    await expect(page.locator('.web-ocard')).toHaveCount(3);
    await page.waitForTimeout(700);
    const tweens = () => page.evaluate(() => gsap.globalTimeline.getChildren(true, true, false).filter(t => t.isActive()).length);
    await page.fill('#wsQty', '12');
    expect(await tweens()).toBe(0);
    expect(await hiddenCards(page)).toBe(0);
  });

  test('cartão abaixo da dobra continua alcançável pelo teclado', async ({ page }) => {
    await openApp(page, 'dashboard');
    await waitMotion(page);
    await dismissDialog(page);
    await page.evaluate(() => { location.hash = '#data'; });
    await page.evaluate(() => { location.hash = '#dashboard'; });
    const last = page.locator('#view a[href="#panel"]').last();
    await last.focus();
    await expect(last).toBeFocused();
    await page.waitForTimeout(900);
    expect(await last.evaluate(el => parseFloat(getComputedStyle(el.closest('.card')).opacity))).toBeGreaterThan(0.99);
  });

  test('com "reduzir movimento", o GSAP nem é baixado', async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: 'reduce' });
    const page = await ctx.newPage();
    let asked = false;
    page.on('request', r => { if (GSAP.test(r.url())) asked = true; });
    const errors = await openApp(page, 'dashboard');
    await page.waitForTimeout(2500);
    expect(asked).toBe(false);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('CDN fora do ar: o app funciona igual e nada fica escondido', async ({ page }) => {
    await page.route(GSAP, r => r.abort());
    const errors = await openApp(page, 'dashboard');
    await page.waitForTimeout(2500);
    await dismissDialog(page);
    await page.evaluate(() => { location.hash = '#restock'; });
    await scrollAll(page);
    expect(await hiddenCards(page)).toBe(0);
    expect(errors).toEqual([]);
  });

  test('girar o celular / redimensionar não deixa cartões presos invisíveis', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await openApp(page, 'dashboard');
    await waitMotion(page);
    await dismissDialog(page);
    await page.evaluate(() => { location.hash = '#data'; });
    await page.evaluate(() => { location.hash = '#restock'; });
    await page.waitForTimeout(300);
    await page.setViewportSize({ width: 600, height: 800 });
    await scrollAll(page);
    expect(await hiddenCards(page)).toBe(0);
  });
});
