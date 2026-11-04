const fs = require("fs");
const { test, expect } = require("/e2e-deps/node_modules/@playwright/test");

const EMAIL_FILE = "/emails/emails.jsonl";
const PASSWORD = "senha-bem-longa-1";

function lastCode(email) {
  const lines = fs.readFileSync(EMAIL_FILE, "utf-8").trim().split("\n").map((l) => JSON.parse(l));
  const message = lines.reverse().find((m) => m.to === email);
  return message.body.match(/\d{6}/)[0];
}

async function field(page, label) {
  return page.getByLabel(label, { exact: true }).first();
}

async function fill(page, label, value) {
  await (await field(page, label)).fill(value);
}

async function enter(page, email, name) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Entrar" })).toBeVisible();
  await fill(page, "E-mail", email);
  await fill(page, "Senha", PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  const painel = page.getByRole("heading", { name: "Painel" });
  const wrong = page.getByText("E-mail ou senha incorretos.");
  await expect(painel.or(wrong)).toBeVisible();
  if (await painel.isVisible()) return;
  // Primeira execucao: cria a conta com codigo por e-mail.
  await page.getByRole("button", { name: "Criar conta" }).click();
  await fill(page, "Nome", name);
  await fill(page, "E-mail", email);
  await fill(page, "Senha", PASSWORD);
  await page.getByRole("button", { name: "Enviar código" }).click();
  await expect(page.getByText("O código expira em")).toBeVisible();
  await fill(page, "Código", lastCode(email));
  await page.getByRole("button", { name: "Confirmar" }).click();
  await expect(painel).toBeVisible();
}

async function openMenu(page, name) {
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("link", { name }).click();
}

// O simulador do WebKit nao atualiza o limite de rolagem depois que um formulario fecha.
// Nesse caso o clique vira um evento direto; a rolagem real e conferida no aparelho.
async function tap(locator) {
  await locator.page().waitForLoadState("networkidle");
  try {
    await locator.click({ timeout: 4000 });
  } catch {
    await locator.dispatchEvent("click");
  }
}

function noHorizontalScroll(page) {
  return page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
}

test("o sistema funciona de ponta a ponta", async ({ page }, info) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const stamp = `${info.project.name}-${Date.now()}`;

  await enter(page, "ana@teste.com", "Ana");
  expect(await noHorizontalScroll(page)).toBe(true);

  // Lancamentos: salario e gasto fora do escopo
  await openMenu(page, "Lançamentos");
  await expect(page.getByRole("heading", { name: "Novo lançamento" })).toBeVisible();
  await page.getByLabel("Tipo", { exact: true }).first().selectOption("renda");
  await fill(page, "Valor", "abc");
  await page.getByRole("button", { name: "Adicionar" }).click();
  await expect(page.getByText("Valor inválido.")).toBeVisible();
  await fill(page, "Valor", "5.000,00");
  await fill(page, "Descrição", `Salário ${stamp}`);
  await page.getByRole("button", { name: "Adicionar" }).click();
  await expect(page.getByText(`Salário ${stamp}`)).toBeVisible();
  await page.getByLabel("Tipo", { exact: true }).first().selectOption("fora_escopo");
  await fill(page, "Valor", "150,50");
  await fill(page, "Descrição", `Imprevisto ${stamp}`);
  await page.getByRole("button", { name: "Adicionar" }).click();
  await expect(page.getByText(`Imprevisto ${stamp}`)).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // Voltar retorna ao Painel e mostra os novos totais
  await page.getByRole("button", { name: "Voltar" }).click();
  await expect(page.getByRole("heading", { name: "Painel" })).toBeVisible();
  await expect(page.getByText("Renda total")).toBeVisible();
  await expect(page.getByRole("heading", { name: /Fluxo de/ })).toBeVisible();
  await expect(page.locator(".chart svg").first()).toBeVisible();
  if (info.project.name === "pc") await page.screenshot({ path: "test-results/painel-pc.png", fullPage: true });
  if (info.project.name === "iphone") await page.screenshot({ path: "test-results/painel-iphone.png", fullPage: true });

  // Personalizar: esconder um bloco
  await openMenu(page, "Ajustes");
  await page.getByRole("checkbox", { name: "Recebimentos do mês" }).uncheck();
  await page.getByRole("button", { name: "Início" }).click();
  await expect(page.getByRole("heading", { name: "Recebimentos do mês" })).toHaveCount(0);
  await openMenu(page, "Ajustes");
  await page.getByRole("checkbox", { name: "Recebimentos do mês" }).check();
  await page.getByRole("button", { name: "Início" }).click();
  await expect(page.getByRole("heading", { name: "Recebimentos do mês" })).toBeVisible();

  // Objetivo com aviso de orcamento
  await openMenu(page, "Objetivos");
  await fill(page, "Nome", `Viagem ${stamp}`);
  await fill(page, "Valor do objetivo", "1.000.000,00");
  await fill(page, "Prazo em meses", "2");
  await page.getByRole("button", { name: "Avaliar no orçamento" }).click();
  await expect(page.getByText("✕ Compromete")).toBeVisible();
  await page.getByRole("button", { name: "Salvar objetivo" }).click();
  await expect(page.getByText(`Viagem ${stamp}`).first()).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // Desafio pelo multiplicador
  await openMenu(page, "Desafios");
  await fill(page, "Nome do desafio", `Hobby ${stamp}`);
  await fill(page, "Quanto quer gastar", "500,00");
  await fill(page, "Prazo em meses", "4");
  await tap(page.getByRole("button", { name: "Criar desafio" }));
  await expect(page.getByText(`Hobby ${stamp}`).first()).toBeVisible();
  await expect(page.getByText("R$ 2.500,00").first()).toBeVisible();

  // Financiamento com tabela de parcelas
  await openMenu(page, "Dívidas e financiamentos");
  await page.getByRole("button", { name: "Novo financiamento" }).click();
  const form = page.locator("form").last();
  await form.getByLabel("Nome", { exact: true }).fill(`Carro ${stamp}`);
  await form.getByLabel("Valor do bem").fill("50.000,00");
  await form.getByLabel("Juros ao ano (%)").fill("12");
  await form.getByLabel("Prazo em meses").fill("12");
  await form.getByLabel("Conta").selectOption({ index: 1 });
  await form.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText(`Carro ${stamp}`).first()).toBeVisible();
  await tap(page.getByRole("button", { name: "Ver todas as parcelas" }).last());
  await expect(page.getByRole("cell", { name: "12", exact: true }).first()).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // Relatorios
  await openMenu(page, "Relatórios");
  await expect(page.getByRole("heading", { name: /Relatório de/ })).toBeVisible();
  await page.getByRole("button", { name: /Fechar/ }).click();
  await expect(page.getByText(/Registro de .* gravado/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Comparar períodos" })).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  await page.getByRole("combobox", { name: "Regime" }).selectOption("caixa");
  await expect(page.getByText("Caixa: considera só")).toBeVisible();
  await expect(page.getByRole("link", { name: "Baixar resumo (CSV)" })).toBeVisible();

  // Previsao e teto
  await openMenu(page, "Previsão e tetos");
  await expect(page.getByRole("heading", { name: "Previsão de saldo" })).toBeVisible();
  await expect(page.getByText("Menor saldo previsto")).toBeVisible();
  await page.getByRole("button", { name: "Novo teto" }).click();
  await page.locator("form").last().getByLabel("Categoria").selectOption({ label: "Moradia" });
  await page.locator("form").last().getByLabel("Teto mensal").fill("2.000,00");
  await page.locator("form").last().getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText("Moradia").first()).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // Extrato: importa, confirma e nao duplica
  await openMenu(page, "Importar e conciliar");
  const unique = Date.now() % 100000;
  const ofx = `<OFX><STMTTRN><DTPOSTED>20260105<TRNAMT>-12.34<FITID>${stamp}<MEMO>Padaria ${stamp}</STMTTRN></OFX>`;
  const send = () => page.getByLabel("Arquivo do extrato").setInputFiles({ name: `extrato${unique}.ofx`, mimeType: "text/plain", buffer: Buffer.from(ofx) });
  await send();
  await expect(page.getByRole("cell", { name: `Padaria ${stamp}` }).first()).toBeVisible();
  await page.getByRole("button", { name: "Confirmar importação" }).click();
  await expect(page.getByText("1 lançamento(s) criado(s)")).toBeVisible();
  await send();
  await expect(page.getByRole("cell", { name: "Já importada" })).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // Lancamento oculto nao aparece para a outra pessoa
  await openMenu(page, "Lançamentos");
  await page.getByLabel("Tipo", { exact: true }).first().selectOption("gasto");
  await fill(page, "Valor", "99,00");
  await fill(page, "Descrição", `Secreto ${stamp}`);
  await page.getByLabel("Ocultar da outra pessoa").first().check();
  await page.getByRole("button", { name: "Adicionar" }).click();
  await expect(page.getByText(`Secreto ${stamp}`)).toBeVisible();

  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole("button", { name: /Sair/ }).click();

  await enter(page, "bia@teste.com", "Bia");
  await openMenu(page, "Lançamentos");
  await expect(page.getByText(`Salário ${stamp}`)).toBeVisible();
  await expect(page.getByText(`Secreto ${stamp}`)).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("salario com varias datas, freela e divida com aviso, pagamento e desfazer", async ({ page }, info) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("dialog", (dialog) => dialog.accept());
  const stamp = `${info.project.name}-${Date.now()}`;
  await enter(page, "ana@teste.com", "Ana");

  // Tres recebimentos mensais, em datas e valores diferentes
  await openMenu(page, "Lançamentos");
  const income = page.locator("section", { has: page.getByRole("heading", { name: "Salário e outras rendas" }) });
  await income.getByLabel("Nome da renda").fill(`Salário ${stamp}`);
  await income.getByRole("button", { name: "+ Outra data" }).click();
  await income.getByRole("button", { name: "+ Outra data" }).click();
  await income.getByLabel("Valor do recebimento 1").fill("1.000,00");
  await income.getByLabel("Valor do recebimento 2").fill("abc");
  await income.getByLabel("Valor do recebimento 3").fill("700,00");
  await income.getByRole("button", { name: "Salvar renda" }).click();
  await expect(income.getByText("Informe o valor do recebimento 2")).toBeVisible();
  await income.getByLabel("Valor do recebimento 2").fill("500,00");
  await income.getByRole("button", { name: "Salvar renda" }).click();
  await expect(income.getByText("3 recebimento(s) salvo(s)")).toBeVisible();
  const rules = page.locator("section", { has: page.getByRole("heading", { name: "Recorrentes" }) });
  await expect(rules.getByText(`Salário ${stamp}`)).toHaveCount(3);
  expect(await noHorizontalScroll(page)).toBe(true);

  // Freela nao vira regra mensal
  await income.getByLabel("Nome da renda").fill(`Freela ${stamp}`);
  await income.getByLabel("Com que frequência").selectOption("unica");
  await income.getByLabel("Valor do recebimento 1").fill("300,00");
  await income.getByRole("button", { name: "Salvar renda" }).click();
  await expect(income.getByText("1 recebimento(s) salvo(s)")).toBeVisible();
  await expect(rules.getByText(`Freela ${stamp}`)).toHaveCount(0);
  if (info.project.name !== "android") await income.screenshot({ path: `test-results/renda-${info.project.name}.png` });

  // Divida: calendario, tag e situacao
  await openMenu(page, "Dívidas e financiamentos");
  await page.getByRole("button", { name: "Nova dívida" }).click();
  const form = page.locator("form").first();
  await expect(form.getByLabel("Próximo vencimento")).toHaveAttribute("type", "date");
  await expect(form.getByLabel("Total de parcelas")).toHaveCount(0);
  await form.getByLabel("Nome", { exact: true }).fill(`Aluguel ${stamp}`);
  await form.getByLabel("Valor", { exact: true }).fill("500,00");
  await form.getByLabel("Tag").selectOption({ label: "Moradia" });
  await form.getByLabel("Conta").selectOption({ index: 1 });
  await form.getByRole("button", { name: "Salvar" }).click();
  const card = page.locator(".card .card", { hasText: `Aluguel ${stamp}` });
  await expect(card.getByText("! Vence hoje")).toBeVisible();
  await expect(card.getByText("Moradia")).toBeVisible();
  expect(await noHorizontalScroll(page)).toBe(true);

  // O aviso aparece no painel, com atalho para pagar
  await page.getByRole("button", { name: "Início" }).click();
  await page.waitForLoadState("networkidle");
  const more = page.getByRole("button", { name: /Ver mais .* aviso/ });
  if (await more.isVisible()) await more.click();
  const warning = page.getByRole("status").filter({ hasText: `Aluguel ${stamp} vence hoje` });
  await expect(warning).toBeVisible();
  await warning.getByRole("link", { name: "Registrar pagamento" }).click();

  // Pagar muda a tela e troca o botao, sem permitir o clique repetido
  await tap(card.getByRole("button", { name: /Registrar pagamento de/ }));
  await card.getByLabel("Valor pago").fill("480,00");
  await tap(card.getByRole("button", { name: "Confirmar pagamento" }));
  await expect(page.getByText(`Pagamento de R$ 480,00 registrado em Aluguel ${stamp}.`)).toBeVisible();
  await expect(card.getByText("✓ Em dia")).toBeVisible();
  await expect(card.getByText(/último pagamento: R\$\s480,00/)).toBeVisible();
  await expect(card.getByRole("button", { name: /Registrar pagamento de/ })).toHaveCount(0);
  await expect(card.getByRole("button", { name: /Adiantar/ })).toBeVisible();
  if (info.project.name !== "android") await page.screenshot({ path: `test-results/dividas-${info.project.name}.png`, fullPage: true });

  // Desfazer volta ao que era, e sem pagamentos a divida pode ser excluida
  await tap(card.getByRole("button", { name: "Desfazer último pagamento" }));
  await expect(card.getByText("! Vence hoje")).toBeVisible();
  await tap(card.getByRole("button", { name: "Excluir" }));
  await expect(page.getByText(`Aluguel ${stamp} excluída.`)).toBeVisible();
  await expect(card).toHaveCount(0);

  expect(errors).toEqual([]);
});

test("dividas podem ser excluidas uma a uma e em massa, com os pagamentos", async ({ page }, info) => {
  page.on("dialog", (dialog) => dialog.accept());
  const stamp = `${info.project.name}-${Date.now()}`;
  await enter(page, "ana@teste.com", "Ana");
  await openMenu(page, "Dívidas e financiamentos");
  for (const name of ["Um", "Dois", "Tres"]) {
    await tap(page.getByRole("button", { name: "Nova dívida" }));
    const form = page.locator("form").first();
    await form.getByLabel("Nome", { exact: true }).fill(`${name} ${stamp}`);
    await form.getByLabel("Valor", { exact: true }).fill("100,00");
    await form.getByLabel("Conta").selectOption({ index: 1 });
    await tap(form.getByRole("button", { name: "Salvar" }));
    await expect(page.getByText(`${name} ${stamp} cadastrada.`)).toBeVisible();
  }
  // Uma por uma, mesmo com pagamento registrado
  const one = page.locator(".card .card", { hasText: `Um ${stamp}` });
  await tap(one.getByRole("button", { name: /Registrar pagamento de/ }));
  await tap(one.getByRole("button", { name: "Confirmar pagamento" }));
  await expect(one.getByText("✓ Em dia")).toBeVisible();
  await tap(one.getByRole("button", { name: "Excluir" }));
  await expect(page.getByText(`Um ${stamp} excluída.`)).toBeVisible();
  await expect(one).toHaveCount(0);
  // Em massa
  await expect(page.getByRole("button", { name: /Excluir selecionadas/ })).toHaveCount(0);
  await page.getByLabel(`Selecionar Dois ${stamp}`).check();
  await page.getByLabel(`Selecionar Tres ${stamp}`).check();
  await tap(page.getByRole("button", { name: "Excluir selecionadas (2)" }));
  await expect(page.getByText("2 dívida(s) excluída(s).")).toBeVisible();
  await expect(page.getByText(`Dois ${stamp}`)).toHaveCount(0);
  await expect(page.getByText(`Tres ${stamp}`)).toHaveCount(0);
  expect(await noHorizontalScroll(page)).toBe(true);
});

test.describe("versao nova", () => {
  test.use({ serviceWorkers: "block" });

  test("aba aberta antes da atualizacao avisa que ha versao nova", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Entrar" })).toBeVisible();
    await expect(page.getByText("Há uma versão nova do sistema.")).toHaveCount(0);
    await page.route("**/", async (route) => {
      if (route.request().resourceType() !== "fetch") return route.continue();
      const response = await route.fetch();
      const html = (await response.text()).replace(/\/assets\/index-[^"']+\.js/g, "/assets/index-novo.js");
      return route.fulfill({ response, body: html });
    });
    await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
    await expect(page.getByText("Há uma versão nova do sistema.")).toBeVisible();
    await page.unroute("**/");
    await page.getByRole("button", { name: "Atualizar agora" }).click();
    await expect(page.getByRole("heading", { name: "Entrar" })).toBeVisible();
    await expect(page.getByText("Há uma versão nova do sistema.")).toHaveCount(0);
  });
});

test("recarregar mantem os filtros e o botao Voltar do navegador funciona", async ({ page }) => {
  await enter(page, "ana@teste.com", "Ana");
  await openMenu(page, "Lançamentos");
  await page.getByLabel("Buscar").fill("Salário");
  await expect(page).toHaveURL(/busca=/);
  await page.reload();
  await expect(page.getByLabel("Buscar")).toHaveValue("Salário");
  await openMenu(page, "Objetivos");
  await expect(page.getByRole("heading", { name: "Objetivos" })).toBeVisible();
  await page.goBack();
  await expect(page.getByLabel("Buscar")).toHaveValue("Salário");
});

test("o app pode ser instalado e nao guarda dados no cache", async ({ page, request }) => {
  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest.display).toBe("standalone");
  expect((await request.get("/icone-192.png")).ok()).toBe(true);
  expect((await request.get("/icone-512.png")).ok()).toBe(true);
  const worker = await (await request.get("/sw.js")).text();
  expect(worker).toContain('startsWith("/api/")');
  const response = await request.get("/");
  expect(response.headers()["content-security-policy"]).toContain("default-src 'self'");
});
