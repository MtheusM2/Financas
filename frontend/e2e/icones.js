// Gera os icones PNG a partir do SVG. Uso: dentro da imagem do Playwright.
const fs = require("fs");
const { chromium } = require("/e2e-deps/node_modules/@playwright/test");

(async () => {
  const svg = fs.readFileSync("/public/icone.svg", "utf-8");
  const browser = await chromium.launch();
  for (const size of [192, 512]) {
    const page = await browser.newPage({ viewport: { width: size, height: size } });
    await page.setContent(`<style>*{margin:0}svg{display:block;width:${size}px;height:${size}px}</style>${svg}`);
    await page.screenshot({ path: `/public/icone-${size}.png` });
    await page.close();
  }
  await browser.close();
})();
