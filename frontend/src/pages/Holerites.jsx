import { useState } from "react";
import { z } from "zod";
import { api, useApi } from "../api";
import { dateBR, money, parseMoney, today, toInputMoney } from "../format";
import { LineChart } from "../charts";
import { Empty, Form, Loading, Status } from "../ui";
import { useApp } from "../main";
import { accountOptions, flatten, useWritableAccounts } from "./Lancamentos";

const MAX_BYTES = 5_000_000;
const MAX_ITEMS = 80;
const TOTALS = [
  ["total_vencimentos", "Total de vencimentos"], ["total_descontos", "Total de descontos"], ["liquido", "Valor líquido"],
];
const BASES = [
  ["salario_base", "Salário base"], ["base_inss", "Base INSS"], ["base_fgts", "Base FGTS"],
  ["fgts_mes", "FGTS do mês"], ["base_irrf", "Base IRRF"],
];
const ROLES = {
  "": "Não ligar", liquido: "Salário (líquido do holerite)", adiantamento: "Adiantamento",
  beneficio: "Benefício fora do holerite (VR, VT…)", outro: "Outra parte do salário",
};
const ADVANCE = /adiant/i;
const FIELDS = Object.fromEntries([...TOTALS, ...BASES]);
const shortMonth = (key) => `${String(key % 100).padStart(2, "0")}/${String(Math.floor(key / 100)).slice(2)}`;
const MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
const monthText = (key) => (key ? `${MONTHS[(key % 100) - 1]} de ${Math.floor(key / 100)}` : "—");
const toMonthInput = (key) => (key ? `${Math.floor(key / 100)}-${String(key % 100).padStart(2, "0")}` : "");

// Filtro do navegador; o servidor valida tudo de novo.
const cents = z.number({ invalid_type_error: "Valor inválido." }).int().min(0, "Valor não pode ser negativo.").max(10_000_000_000, "Valor alto demais.");
const optionalCents = cents.nullable();
const schema = z.object({
  empresa: z.string().trim().max(160, "Nome da empresa longo demais."),
  cnpj: z.string().trim().max(20, "CNPJ inválido."),
  referencia: z.number({ invalid_type_error: "Informe o mês de referência." }).int().refine((v) => v % 100 >= 1 && v % 100 <= 12, "Mês inválido."),
  itens: z.array(z.object({
    codigo: z.string().trim().max(12),
    descricao: z.string().trim().min(1, "Toda linha precisa de descrição.").max(80, "Descrição longa demais."),
    referencia: z.string().trim().max(12),
    tipo: z.enum(["provento", "desconto"]),
    valor: cents,
  })).max(MAX_ITEMS),
  total_vencimentos: cents, total_descontos: cents, liquido: cents,
  salario_base: optionalCents, base_inss: optionalCents, base_fgts: optionalCents, fgts_mes: optionalCents, base_irrf: optionalCents,
});

async function toBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function MoneyInput({ label, value, onChange }) {
  const [text, setText] = useState(toInputMoney(value));
  const input = (
      <input aria-label={label || "Valor"} inputMode="decimal" value={text} placeholder="0,00" onChange={(e) => {
        setText(e.target.value);
        const parsed = parseMoney(e.target.value);
        onChange(parsed === null ? null : parsed);
      }} />
  );
  return label ? <label className="field"><span>{label}</span>{input}</label> : input;
}

function Review({ initial, accounts, categories, onSaved, onDiscard }) {
  const { user } = useApp();
  const [slip, setSlip] = useState(() => ({ ...initial, itens: initial.itens.map((i) => ({ ...i })) }));
  const candidates = initial.candidatos || [];
  const [links, setLinks] = useState(() => Object.fromEntries(candidates.map((c) => [c.id, c.sugestao || ""])));
  const salaryLinked = Object.values(links).includes("liquido");
  const [launchChoice, setLaunch] = useState(!initial.ja_importado && !candidates.some((c) => c.sugestao === "liquido"));
  const launch = launchChoice && !salaryLinked;
  const unknown = initial.desconhecidos || [];
  const [learn, setLearn] = useState({});
  const [version, setVersion] = useState(0); // redesenha os campos de valor quando a escolha muda um total
  const teach = (index, field) => {
    const next = { ...learn, [index]: field };
    setLearn(next);
    if (field) { set({ [field]: unknown[index].valor }); setVersion((v) => v + 1); }
  };
  const [income, setIncome] = useState({
    account_id: String((accounts.find((a) => a.dono === user.id) || accounts[0] || {}).id ?? ""),
    date: today(), category_id: "", hidden: false,
  });
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (changes) => setSlip({ ...slip, ...changes });
  const setItem = (index, changes) => set({ itens: slip.itens.map((i, n) => (n === index ? { ...i, ...changes } : i)) });
  const earned = slip.itens.filter((i) => i.tipo === "provento").reduce((s, i) => s + (i.valor || 0), 0);
  const deducted = slip.itens.filter((i) => i.tipo === "desconto").reduce((s, i) => s + (i.valor || 0), 0);
  const checks = [
    earned === slip.total_vencimentos ? null : "A soma dos vencimentos não bate com o total.",
    deducted === slip.total_descontos ? null : "A soma dos descontos não bate com o total.",
    (slip.total_vencimentos ?? 0) - (slip.total_descontos ?? 0) === slip.liquido ? null : "Vencimentos menos descontos não dá o líquido.",
  ].filter(Boolean);

  const save = async () => {
    setFailure(null);
    const parsed = schema.safeParse(slip);
    if (!parsed.success) { setFailure(parsed.error.issues[0].message); return; }
    if (launch && !income.account_id) { setFailure("Escolha a conta onde o salário caiu."); return; }
    if (launch && !/^\d{4}-\d{2}-\d{2}$/.test(income.date)) { setFailure("Informe a data em que o salário caiu."); return; }
    setBusy(true);
    try {
      const aprender = Object.entries(learn).filter(([, f]) => f).map(([i, f]) => ({ rotulo: unknown[i].rotulo, campo: f }));
      const body = { ...parsed.data, aprender, vinculos: Object.entries(links).filter(([, p]) => p).map(([id, p]) => ({ transaction_id: Number(id), papel: p })) };
      if (launch) {
        body.lancar_renda = { account_id: Number(income.account_id), date: income.date, hidden: income.hidden,
          category_id: income.category_id ? Number(income.category_id) : null };
      }
      await api("/holerites", { method: "POST", body });
      onSaved(`Holerite de ${monthText(parsed.data.referencia)} gravado${launch ? " e o líquido lançado como renda" : ""}.`);
    } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  };

  return (
    <div className="card" style={{ marginTop: 12 }}>
      <h3>Revise o holerite de {monthText(slip.referencia)}</h3>
      {initial.ja_importado && <div className="error-box" role="alert">Este holerite já foi importado antes.</div>}
      {initial.avisos.length > 0
        ? <Status level="atencao">Confira com atenção: {initial.avisos.join(" ")}</Status>
        : <Status level="feito">As somas do holerite conferem.</Status>}
      <div className="form-grid" style={{ marginTop: 10 }}>
        <label className="field"><span>Empresa</span><input value={slip.empresa} maxLength={160} onChange={(e) => set({ empresa: e.target.value })} /></label>
        <label className="field"><span>CNPJ</span><input value={slip.cnpj} maxLength={20} onChange={(e) => set({ cnpj: e.target.value })} /></label>
        <label className="field"><span>Mês de referência</span>
          <input type="month" value={toMonthInput(slip.referencia)} onChange={(e) => {
            const [y, m] = e.target.value.split("-").map(Number);
            set({ referencia: y && m ? y * 100 + m : null });
          }} />
        </label>
      </div>
      {/* Uma linha por item, que quebra em duas no celular. */}
      <div style={{ marginTop: 10, display: "grid", gap: 8 }}>
        {slip.itens.map((item, index) => (
          <div key={index} className="row" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
            <input aria-label="Descrição" style={{ flex: "2 1 220px", minWidth: 0 }} value={item.descricao} maxLength={80}
              onChange={(e) => setItem(index, { descricao: e.target.value })} />
            {item.referencia && <span className="muted" title="Referência">Ref. {item.referencia}</span>}
            <select aria-label="Tipo" style={{ flex: "1 1 120px" }} value={item.tipo} onChange={(e) => setItem(index, { tipo: e.target.value })}>
              <option value="provento">Vencimento</option><option value="desconto">Desconto</option>
            </select>
            <div style={{ flex: "1 1 110px", minWidth: 0 }}><MoneyInput label="" value={item.valor} onChange={(v) => setItem(index, { valor: v })} /></div>
            <button type="button" className="small" onClick={() => set({ itens: slip.itens.filter((_, n) => n !== index) })}>Tirar</button>
          </div>
        ))}
      </div>
      <button type="button" className="small" style={{ marginTop: 8 }} disabled={slip.itens.length >= MAX_ITEMS}
        onClick={() => set({ itens: [...slip.itens, { codigo: "", descricao: "", referencia: "", tipo: "desconto", valor: 0 }] })}>Adicionar linha</button>
      <div className="form-grid" style={{ marginTop: 10 }}>
        {TOTALS.map(([key, label]) => <MoneyInput key={`${key}-${version}`} label={label} value={slip[key]} onChange={(v) => set({ [key]: v })} />)}
        {BASES.map(([key, label]) => <MoneyInput key={`${key}-${version}`} label={label} value={slip[key]} onChange={(v) => set({ [key]: v })} />)}
      </div>
      {checks.length > 0 && <div className="error-box" role="alert">{checks.join(" ")}</div>}
      {unknown.length > 0 && (
        <div style={{ marginTop: 14 }}>
          <h3>Valores que o leitor não reconheceu</h3>
          <p className="muted">Se algum for um dos campos acima, escolha qual. O sistema aprende esse nome e acerta sozinho nos próximos holerites.</p>
          <div style={{ display: "grid", gap: 8 }}>
            {unknown.map((u, index) => (
              <div key={index} className="row">
                <span style={{ flex: "2 1 200px" }}>"{u.rotulo}": <b>{money(u.valor)}</b></span>
                <select aria-label={`O que é ${u.rotulo}`} style={{ flex: "1 1 200px" }} value={learn[index] || ""} onChange={(e) => teach(index, e.target.value)}>
                  <option value="">Ignorar</option>
                  {Object.entries(FIELDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
            ))}
          </div>
        </div>
      )}
      {(initial.mudancas || []).length > 0 && (
        <div style={{ marginTop: 14 }}>
          <Status level="atencao">Mudou em relação ao holerite anterior desta empresa:</Status>
          <ChangeList items={initial.mudancas} />
        </div>
      )}
      <LinkSection slip={slip} candidates={candidates} links={links} setLinks={setLinks} />
      <div style={{ marginTop: 10 }}>
        {salaryLinked && <p className="muted">O salário já está ligado a uma renda lançada, então o holerite não cria renda nova.</p>}
        {!salaryLinked && <label className="field check"><input type="checkbox" checked={launch} onChange={(e) => setLaunch(e.target.checked)} />
          <span>Lançar o líquido ({money(slip.liquido)}) como renda recebida</span></label>}
        {launch && (
          <>
            <p className="muted">Se o salário já entra por uma renda mensal cadastrada, deixe desmarcado para não contar duas vezes.</p>
            <div className="form-grid">
              <label className="field"><span>Conta</span>
                <select value={income.account_id} onChange={(e) => setIncome({ ...income, account_id: e.target.value })}>
                  {accountOptions(accounts).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select></label>
              <label className="field"><span>Data em que caiu</span>
                <input type="date" value={income.date} onChange={(e) => setIncome({ ...income, date: e.target.value })} /></label>
              <label className="field"><span>Categoria</span>
                <select value={income.category_id} onChange={(e) => setIncome({ ...income, category_id: e.target.value })}>
                  <option value="">Sem categoria</option>{categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select></label>
              <label className="field check"><input type="checkbox" checked={income.hidden} onChange={(e) => setIncome({ ...income, hidden: e.target.checked })} />
                <span>Ocultar o lançamento da outra pessoa</span></label>
            </div>
          </>
        )}
      </div>
      {failure && <div className="error-box" role="alert">{failure}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button type="button" className="primary" disabled={busy} onClick={save}>{busy ? "Aguarde…" : "Gravar holerite"}</button>
        <button type="button" onClick={onDiscard}>Descartar</button>
      </div>
    </div>
  );
}

function ChangeList({ items }) {
  return (
    <ul style={{ margin: "6px 0" }}>
      {items.map((c, n) => (
        <li key={n}>{c.texto}{c.de !== undefined ? `: de ${money(c.de)} para ${money(c.para)}` : c.valor !== undefined ? ` (${money(c.valor)})` : ""}</li>
      ))}
    </ul>
  );
}

function Fgts({ fgts, reload }) {
  return (
    <section className="card">
      <h2>FGTS</h2>
      <p className="muted">Informe o saldo que aparece no app FGTS da Caixa. O sistema soma os depósitos dos seus holerites (que caem até o dia 20 do mês seguinte) e compara os dois controles.</p>
      <div className="row" style={{ gap: 16, margin: "8px 0" }}>
        <div><div className="muted">Saldo na Caixa{fgts.data_caixa ? ` em ${dateBR(fgts.data_caixa)}` : ""}</div><b>{money(fgts.saldo_caixa)}</b></div>
        <div><div className="muted">Depósitos dos holerites desde então</div><b>{money(fgts.depositos_desde)}</b></div>
        <div><div className="muted">Saldo calculado hoje</div><b>{money(fgts.saldo_calculado)}</b></div>
        {fgts.a_depositar > 0 && <div><div className="muted">Ainda vai cair</div><b>{money(fgts.a_depositar)}</b></div>}
      </div>
      <Form
        submit="Informar saldo da Caixa"
        fields={[
          { name: "date", type: "date", label: "Data do extrato", required: true },
          { name: "balance_cents", type: "money", label: "Saldo na Caixa", required: true },
        ]}
        onSubmit={async (v) => { await api("/holerites/fgts", { method: "POST", body: v }); reload(); }}
      />
      {fgts.historico.length > 0 && (
        <div className="table-wrap" style={{ marginTop: 12 }}><table>
          <thead><tr><th>Data</th><th className="num">Caixa</th><th className="num">Esperado</th><th className="num">Diferença</th><th /></tr></thead>
          <tbody>{fgts.historico.map((h) => (
            <tr key={h.id}>
              <td>{dateBR(h.data)}</td><td className="num">{money(h.saldo)}</td><td className="num">{money(h.esperado)}</td>
              <td className="num">{h.diferenca === null ? "—" : h.diferenca < 0 ? `! ${money(h.diferenca)}` : money(h.diferenca)}</td>
              <td><button type="button" className="small" onClick={async () => { await api(`/holerites/fgts/${h.id}`, { method: "DELETE" }); reload(); }}>Apagar</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {fgts.depositos.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <h3>FGTS de cada holerite</h3>
          <div style={{ display: "grid", gap: 6 }}>
            {fgts.depositos.map((d) => (
              <div key={d.referencia} className="row" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 6, justifyContent: "space-between" }}>
                <span>{monthText(d.referencia)} · <b>{money(d.valor)}</b> · cai até {dateBR(d.data)}</span>
                <span className="muted">{d.situacao === "na_caixa" ? `Já está no saldo da Caixa de ${dateBR(fgts.data_caixa)}`
                  : d.situacao === "somado" ? "Somado ao saldo calculado" : "Ainda vai cair"}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <p className="muted">O depósito que caiu antes da data do saldo informado já está dentro dele, por isso não é somado de novo. Os próximos holerites vão somando a partir dessa data.</p>
      {fgts.historico.some((h) => h.diferenca !== null && h.diferenca < 0) && (
        <Status level="atencao">A Caixa mostra menos do que os holerites dizem que foi depositado. Pode faltar um depósito: confira o extrato do FGTS.</Status>
      )}
      <p className="muted">Diferença positiva costuma ser o rendimento do FGTS (juros e distribuição de lucro).</p>
    </section>
  );
}

function Analysis({ state }) {
  return (
    <Loading state={state}>{(data) => {
      const months = data.meses;
      const labels = months.map((m) => shortMonth(m.referencia));
      const names = [];
      months.forEach((m) => m.itens.forEach((i) => { if (!names.some((n) => n.key === `${i.tipo}:${i.descricao}`)) names.push({ key: `${i.tipo}:${i.descricao}`, ...i }); }));
      const last = months[months.length - 1];
      return (
        <>
          {months.length > 0 && (
            <section className="card">
              <h2>Análise dos holerites</h2>
              {last?.mudancas.length > 0
                ? <><Status level="atencao">No último holerite ({monthText(last.referencia)}) mudou:</Status><ChangeList items={last.mudancas} /></>
                : <Status level="feito">O último holerite não teve mudanças em relação ao anterior.</Status>}
              {months.length > 1 && (
                <div style={{ marginTop: 12 }}>
                  <LineChart data={months} labels={labels} title={(i) => monthText(months[i].referencia)} series={[
                    { key: "bruto", label: "Bruto", color: "var(--s1)" },
                    { key: "descontos", label: "Descontos", color: "var(--s2)" },
                    { key: "liquido", label: "Líquido", color: "var(--s3)" },
                    { key: "fgts_mes", label: "FGTS", color: "var(--s4)" },
                  ]} />
                </div>
              )}
              <div className="table-wrap" style={{ marginTop: 12 }}><table>
                <thead><tr><th>Item</th>{labels.map((l) => <th key={l} className="num">{l}</th>)}</tr></thead>
                <tbody>
                  {names.map((n) => (
                    <tr key={n.key}><td>{n.tipo === "desconto" ? "−\u00a0" : "+\u00a0"}{n.descricao}</td>
                      {months.map((m) => {
                        const value = m.itens.filter((i) => i.tipo === n.tipo && i.descricao === n.descricao).reduce((s, i) => s + i.valor, 0);
                        return <td key={m.id} className="num">{value ? money(value) : "—"}</td>;
                      })}
                    </tr>
                  ))}
                  <tr><td><b>Líquido</b></td>{months.map((m) => <td key={m.id} className="num"><b>{money(m.liquido)}</b></td>)}</tr>
                  <tr><td>FGTS do mês</td>{months.map((m) => <td key={m.id} className="num">{money(m.fgts_mes)}</td>)}</tr>
                </tbody>
              </table></div>
            </section>
          )}
          <Fgts fgts={data.fgts} reload={state.reload} />
        </>
      );
    }}</Loading>
  );
}

function LinkSection({ slip, candidates, links, setLinks }) {
  const advance = slip.itens.filter((i) => i.tipo === "desconto" && ADVANCE.test(i.descricao)).reduce((s, i) => s + (i.valor || 0), 0);
  const expected = (slip.liquido || 0) + advance;
  const linked = candidates.filter((c) => links[c.id]);
  const salary = linked.filter((c) => links[c.id] !== "beneficio").reduce((s, c) => s + c.valor, 0);
  const benefits = linked.filter((c) => links[c.id] === "beneficio").reduce((s, c) => s + c.valor, 0);
  return (
    <div style={{ marginTop: 14 }}>
      <h3>Ligar ao que você já lançou</h3>
      {candidates.length === 0 ? <p className="muted">Nenhuma renda sua lançada perto desse mês. Se quiser, lance o líquido abaixo.</p> : (
        <>
          <p className="muted">Rendas que você lançou entre o mês do holerite e o pagamento. O sistema já sugeriu pelo valor; confira.</p>
          <div style={{ display: "grid", gap: 8 }}>
            {candidates.map((c) => (
              <div key={c.id} className="row" style={{ borderBottom: "1px solid var(--border)", paddingBottom: 8 }}>
                <span style={{ flex: "2 1 200px" }}>{dateBR(c.data)} · {c.descricao || "Renda"} · <b>{money(c.valor)}</b></span>
                <select aria-label={`Ligar ${c.descricao}`} style={{ flex: "1 1 200px" }} value={links[c.id]} onChange={(e) => setLinks({ ...links, [c.id]: e.target.value })}>
                  {Object.entries(ROLES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </div>
            ))}
          </div>
          <p style={{ marginTop: 8 }}>
            Pelo holerite deveriam cair <b>{money(expected)}</b>{advance ? ` (líquido ${money(slip.liquido)} + adiantamento ${money(advance)})` : ""}.
            {" "}Ligado como salário: <b>{money(salary)}</b>{benefits ? `. Benefícios fora do holerite: ${money(benefits)}` : ""}.
          </p>
          {linked.length > 0 && (salary === expected
            ? <Status level="feito">O que você lançou bate com o holerite.</Status>
            : <Status level="atencao">Diferença de {money(salary - expected)} entre o lançado e o holerite.</Status>)}
        </>
      )}
    </div>
  );
}

export function Importer({ onDone, footer }) {
  const accounts = useWritableAccounts();
  const categories = flatten(useApi("/contas/categorias").data || []);
  const [slips, setSlips] = useState([]);
  const [message, setMessage] = useState(null);
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  const read = async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    setFailure(null); setMessage(null); setSlips([]);
    if (!file) return;
    if (file.size > MAX_BYTES) { setFailure("Arquivo maior que 5 MB."); return; }
    if (!/\.pdf$/i.test(file.name) && file.type !== "application/pdf") { setFailure("Envie o holerite em PDF."); return; }
    setBusy(true);
    try {
      const data = await api("/holerites/previa", { method: "POST", body: { content_base64: await toBase64(file) } });
      setSlips(data.holerites.map((s, n) => ({ ...s, chave: `${Date.now()}-${n}` })));
    } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  };

  const remove = (key) => setSlips((all) => all.filter((s) => s.chave !== key));

  return (
    <section className="card">
      <h2>Importar holerite</h2>
      <p className="muted">Envie o PDF do holerite (recibo de pagamento) que a empresa manda. O sistema lê os valores, você confere e só então grava. O arquivo não fica guardado, e o holerite só aparece para você.</p>
      <label className="field"><span>Arquivo PDF</span>
        <input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={read} /></label>
      {busy && <p className="muted">Lendo o holerite…</p>}
      {message && <div style={{ marginTop: 10 }}><Status level="feito">{message}</Status></div>}
      {failure && <div className="error-box" role="alert">{failure}</div>}
      {slips.map((s) => (
        <Review key={s.chave} initial={s} accounts={accounts} categories={categories}
          onSaved={(text) => { setMessage(text); remove(s.chave); onDone(); }} onDiscard={() => remove(s.chave)} />
      ))}
      {footer}
    </section>
  );
}

function History({ state }) {
  const [open, setOpen] = useState(null);
  const remove = async (slip) => {
    if (!window.confirm(`Apagar o holerite de ${monthText(slip.referencia)}? O lançamento de renda, se houver, continua em Lançamentos.`)) return;
    await api(`/holerites/${slip.id}`, { method: "DELETE" });
    state.reload();
  };
  return (
    <section className="card">
      <h2>Meus holerites</h2>
      <Loading state={state}>{(rows) => (rows.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Mês</th><th>Empresa</th><th className="num">Bruto</th><th className="num">Descontos</th><th className="num">Líquido</th><th className="num">FGTS</th><th /></tr></thead>
          <tbody>{rows.flatMap((p) => [
            <tr key={p.id}>
              <td>{monthText(p.referencia)}</td><td>{p.empresa || "—"}</td>
              <td className="num">{money(p.total_vencimentos)}</td><td className="num">{money(p.total_descontos)}</td>
              <td className="num"><b>{money(p.liquido)}</b>{p.vinculos?.length > 0 && <div className="muted">{p.resumo.confere ? "✓ ligado" : p.resumo.diferenca < 0 ? `falta ligar ${money(-p.resumo.diferenca)}` : `ligado a mais ${money(p.resumo.diferenca)}`}</div>}</td><td className="num">{money(p.fgts_mes)}</td>
              <td><div className="row" style={{ flexWrap: "nowrap" }}>
                <button type="button" className="small" aria-expanded={open === p.id} onClick={() => setOpen(open === p.id ? null : p.id)}>{open === p.id ? "Fechar" : "Itens"}</button>
                <button type="button" className="small" onClick={() => remove(p)}>Apagar</button>
              </div></td>
            </tr>,
            open === p.id && (
              <tr key={`${p.id}-itens`}><td colSpan={7}>
                <ul>{p.itens.map((i, n) => <li key={n}>{i.descricao}: {i.tipo === "desconto" ? "−" : "+"}{money(i.valor)}</li>)}</ul>
                {p.vinculos?.length > 0 && <p className="muted">Ligado a: {p.vinculos.map((v) => `${v.descricao || "renda"} (${ROLES[v.papel]}, ${money(v.valor)})`).join("; ")}</p>}
                <p className="muted">Base INSS {money(p.base_inss)} · Base FGTS {money(p.base_fgts)} · Base IRRF {money(p.base_irrf)}</p>
              </td></tr>
            ),
          ].filter(Boolean))}</tbody>
        </table></div>
      ) : <Empty>Nenhum holerite importado ainda.</Empty>)}</Loading>
    </section>
  );
}

export default function Holerites() {
  const state = useApi("/holerites");
  const analysis = useApi("/holerites/analise/resumo");
  const reload = () => { state.reload(); analysis.reload(); };
  return (
    <>
      <h1>Holerites</h1>
      <Importer onDone={reload} />
      <Analysis state={analysis} />
      <History state={{ ...state, reload }} />
    </>
  );
}
