// Testes lógicos, de usabilidade, de segurança e de desempenho da interface.
const { test, expect } = require('@playwright/test');
const { SCREENS, openApp, dismissDialog } = require('./helpers');

test.describe('Estabilidade: todas as telas', () => {
  for (const s of SCREENS) {
    test(`tela #${s} abre sem erros de JavaScript`, async ({ page }) => {
      const errors = await openApp(page, s);
      await expect(page.locator('#title')).not.toBeEmpty();
      expect(errors, errors.join('\n')).toEqual([]);
    });
  }
});

test.describe('Busca de preços online', () => {
  test('busca mostra ofertas ordenadas do menor para o maior preço', async ({ page }) => {
    const errors = await openApp(page, 'search');
    await dismissDialog(page);
    await page.fill('#wsQ', 'Soja');
    await page.press('#wsQ', 'Enter');
    const cards = page.locator('.web-ocard');
    await expect(cards).toHaveCount(3);
    const prices = await page.locator('.web-ocard-unit').allTextContents();
    const nums = prices.map(t => Number(t.replace(/[^\d,]/g, '').replace(',', '.')));
    expect(nums).toEqual([...nums].sort((a, b) => a - b));
    await expect(cards.first()).toHaveClass(/best/);
    expect(errors, errors.join('\n')).toEqual([]);
  });

  test('segurança: HTML vindo da internet é escapado (sem XSS)', async ({ page }) => {
    await openApp(page, 'search');
    await dismissDialog(page);
    await page.fill('#wsQ', 'Soja');
    await page.press('#wsQ', 'Enter');
    await expect(page.locator('.web-ocard')).toHaveCount(3);
    expect(await page.evaluate(() => window.__xss)).toBeUndefined();
    await expect(page.getByText('<img src=x onerror', { exact: false })).toBeVisible();
    // Links "javascript:" nunca devem virar um link clicável.
    expect(await page.locator('#wsResults a[href^="javascript:"]').count()).toBe(0);
  });

  test('servidor fora do ar: mensagem clara, sem travar a tela', async ({ page }) => {
    const errors = await openApp(page, 'search', { api: 'down' });
    await dismissDialog(page);
    await page.fill('#wsQ', 'Soja');
    await page.press('#wsQ', 'Enter');
    await expect(page.locator('#wsResults')).toContainText('Nenhuma oferta real encontrada');
    expect(errors, errors.join('\n')).toEqual([]);
  });

  test('fechar compra registra o pedido no estoque', async ({ page }) => {
    await openApp(page, 'search');
    await dismissDialog(page);
    await page.fill('#wsQ', 'Soja');
    await page.press('#wsQ', 'Enter');
    await expect(page.locator('.web-ocard')).toHaveCount(3);
    const before = await page.evaluate(() => JSON.parse(localStorage.getItem('iec_html_v1')).purchases.length);
    await page.locator('.web-ocard').first().locator('[data-act="wsBuyNow"]').click();
    await expect(page.locator('#dlg[open]')).toBeVisible();
    const openStore = page.locator('#wsOpenStore');
    if (await openStore.count()) await openStore.uncheck();
    await page.locator('#dlgOk').click();
    await expect(page).toHaveURL(/#stock/);
    const after = await page.evaluate(() => JSON.parse(localStorage.getItem('iec_html_v1')).purchases);
    expect(after.length).toBe(before + 1);
    expect(after[after.length - 1].lines[0].p).toBe(199.9);
  });
});

test.describe('Desempenho e re-render', () => {
  test('a tela inicial é desenhada uma única vez no carregamento', async ({ page }) => {
    await page.addInitScript(() => {
      window.__viewReplaces = 0;
      new MutationObserver((_, obs) => {
        const v = document.getElementById('view'); if (!v) return; obs.disconnect();
        new MutationObserver(recs => { recs.forEach(r => { if (r.target === v && r.removedNodes.length > 2) window.__viewReplaces++; }); })
          .observe(v, { childList: true });
      }).observe(document, { childList: true, subtree: true });
    });
    await openApp(page, 'dashboard');
    await page.waitForTimeout(300);
    expect(await page.evaluate(() => window.__viewReplaces)).toBe(0);
  });

  test('voltar à tela de busca várias vezes não acumula listeners', async ({ page }) => {
    await page.addInitScript(() => {
      window.__docClicks = 0;
      const orig = document.addEventListener.bind(document);
      document.addEventListener = (t, ...a) => { if (t === 'click') window.__docClicks++; return orig(t, ...a); };
    });
    await openApp(page, 'search');
    await dismissDialog(page);
    const first = await page.evaluate(() => window.__docClicks);
    for (let i = 0; i < 4; i++) {
      await page.evaluate(() => { location.hash = '#dashboard'; });
      await page.evaluate(() => { location.hash = '#search'; });
    }
    await expect(page.locator('#wsQ')).toBeVisible();
    expect(await page.evaluate(() => window.__docClicks)).toBe(first);
  });
});

test.describe('Usabilidade', () => {
  for (const s of ['dashboard', 'search', 'stock']) {
    test(`#${s} não tem rolagem horizontal`, async ({ page }) => {
      await openApp(page, s);
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(over).toBeLessThanOrEqual(1);
    });
  }

  test('atalho Ctrl+K foca a busca geral', async ({ page, isMobile }) => {
    test.skip(isMobile, 'atalho de teclado só faz sentido no desktop');
    await openApp(page, 'dashboard');
    await dismissDialog(page);
    await page.keyboard.press('Control+k');
    await expect(page.locator('#gs')).toBeFocused();
  });
});
