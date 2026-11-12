// Revisión visual/estructural del panel (/, /lab, /hmi, /lora) con Playwright.
// Uso: NODE_PATH=$(npm root -g) node tablero/herramientas/capturas_panel.js [url_base] [carpeta_capturas]
// Comprueba: sin scroll horizontal, sin solapes en la botonera del 3D, sin errores no capturados,
// y el aviso de «3D no exportado» en /lab cuando el servidor 8091 no responde.
// Con PANEL_COOKIE='docente=<ficha>' (modo docente) revisa ademas el bloque de la L10 («MONTAR SOLUCION
// COMPLETA», sliders, «Asi debe salir») a 1440 y 390 px: sin scroll horizontal de pagina ni elementos que lo
// desborden, y deja las capturas lora_docente_<ancho>.png.
const { chromium } = require('playwright');
const fs = require('fs');
const BASE = process.argv[2] || 'http://127.0.0.1:8090';
const OUT = process.argv[3] || '/tmp/claude-0/web';
const PAGINAS = ['/', '/lab', '/hmi', '/lora'];
const TAMS = [[1440, 900], [1024, 768], [768, 1024], [390, 844]];
const solapan = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch();
  const filas = [];
  for (const p of PAGINAS) for (const [w, h] of TAMS) {
    const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
    const pg = await ctx.newPage();
    const errores = [], consola = [];
    pg.on('pageerror', e => errores.push(e.message));
    pg.on('console', m => { if (m.type() === 'error' && !/Failed to load resource|ERR_|net::/.test(m.text())) consola.push(m.text()); });
    await pg.goto(BASE + p, { waitUntil: 'load' });
    await pg.waitForTimeout(p === '/lab' ? 2500 : 1200);
    const r = await pg.evaluate(() => {
      const box = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null;
        const q = e.getBoundingClientRect(); return { left: q.left, right: q.right, top: q.top, bottom: q.bottom }; };
      const doc = document.documentElement;
      const botones = [...document.querySelectorAll('.vistas button')].map(e => e.getBoundingClientRect()).map(q => ({ left: q.left, right: q.right, top: q.top, bottom: q.bottom }));
      const msg = document.querySelector('#aviso3d');
      return { sw: Math.max(doc.scrollWidth, document.body.scrollWidth), vw: window.innerWidth,
               ayuda: box('.ayuda3d'), botones, aviso: !!(msg && msg.getClientRects().length && /no est/.test(msg.textContent)) };
    });
    let ov = '-';
    if (p === '/lab') ov = r.ayuda && r.botones.some(x => solapan(x, r.ayuda)) ? 'SOLAPA' : 'ok';
    await pg.screenshot({ path: `${OUT}/${p === '/' ? 'index' : p.slice(1)}_${w}.png`, fullPage: false });
    filas.push({ pagina: p, ancho: w, scrollH: r.sw <= r.vw ? 'ok' : `${r.sw}>${r.vw}`, solape3D: ov,
                 aviso3D: p === '/lab' ? (r.aviso ? 'visible' : 'NO') : '-', errores: errores.length + consola.length });
    if (errores.length || consola.length) console.log(p, w, errores.concat(consola));
    await ctx.close();
  }
  let docFalla = false;
  if (process.env.PANEL_COOKIE) {
    const [nombre, valor] = process.env.PANEL_COOKIE.split('=');
    const u = new URL(BASE);
    const filasD = [];
    for (const [w, h] of [[1440, 900], [390, 844]]) {
      const ctx = await b.newContext({ viewport: { width: w, height: h } });
      await ctx.addCookies([{ name: nombre, value: valor, domain: u.hostname, path: '/' }]);
      await ctx.addInitScript(() => { try { localStorage.setItem('practica', 'L10'); } catch (_) {} });
      const pg = await ctx.newPage();
      const errores = [];
      pg.on('pageerror', e => errores.push(e.message));
      await pg.goto(BASE + '/lab', { waitUntil: 'load' });
      await pg.waitForSelector('#lora-doc', { timeout: 15000 }).catch(() => {});
      await pg.waitForTimeout(3500);
      const r = await pg.evaluate(() => {
        const bl = document.querySelector('#lora-doc'); if (!bl) return null;
        const doc = document.documentElement, q = bl.getBoundingClientRect();
        const fuera = [...bl.querySelectorAll('*')].filter(e => !e.closest('.tabla-ul') && e.getBoundingClientRect().right > window.innerWidth + 1).map(e => e.tagName + '.' + e.className + '@' + Math.round(e.getBoundingClientRect().right));
        return { sw: Math.max(doc.scrollWidth, document.body.scrollWidth), vw: window.innerWidth, ancho: Math.round(q.width), fuera: fuera.slice(0, 5),
                 filas: document.querySelectorAll('#lora-cadena li').length, pasos: document.querySelectorAll('#lora-pasos li').length,
                 sliders: document.querySelectorAll('#lora-doc input[type=range]').length, botones: [...bl.querySelectorAll('button,a.boton')].map(e => e.textContent.trim().slice(0, 40)) };
      });
      if (r) { await (await pg.$('#lora-doc')).scrollIntoViewIfNeeded(); await pg.screenshot({ path: `${OUT}/lora_docente_${w}.png`, fullPage: true }); }
      filasD.push({ ancho: w, bloque: r ? 'ok' : 'NO', scrollH: r && r.sw <= r.vw ? 'ok' : (r ? `${r.sw}>${r.vw}` : '-'), desborda: r ? r.fuera.length : '-',
                    cadena: r ? r.filas : 0, pasos: r ? r.pasos : 0, sliders: r ? r.sliders : 0, errores: errores.length });
      if (errores.length) console.log('L10 docente', w, errores);
      if (r) console.log(w, JSON.stringify(r.botones));
      await ctx.close();
    }
    console.table(filasD);
    docFalla = filasD.some(f => f.bloque !== 'ok' || f.scrollH !== 'ok' || f.desborda || f.errores || f.sliders !== 2);
  }
  await b.close();
  console.table(filas);
  process.exit(docFalla || filas.some(f => f.scrollH !== 'ok' || f.solape3D === 'SOLAPA' || f.aviso3D === 'NO' || f.errores) ? 1 : 0);
})();
