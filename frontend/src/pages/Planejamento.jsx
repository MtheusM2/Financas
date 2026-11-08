import { useState } from "react";
import { api, query, useApi } from "../api";
import { BarChart, LineChart } from "../charts";
import { dateBR, money, monthLabel, monthName } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Progress, Status, Tile } from "../ui";
import { flatten } from "./Lancamentos";

const LABEL = { ok: "✓ Dentro do teto", perto: "! Perto do limite", estourou: "✕ Estourou" };
const TONE = { ok: "var(--good)", perto: "var(--warning)", estourou: "var(--critical)" };

export function Forecast() {
  const { scope } = useApp();
  const [months, setMonths] = useState(6);
  const [plans, setPlans] = useState(false);
  const [view, setView] = useState("meses");
  const state = useApi(`/previsao${query({ meses: months, incluir_planos: plans ? "true" : "", escopo: scope })}`);
  return (
    <section className="card">
      <div className="row between">
        <h2>Previsão de saldo</h2>
        <div className="row">
          <select style={{ width: "auto" }} aria-label="Ver por" value={view} onChange={(e) => setView(e.target.value)}>
            <option value="meses">Por mês</option><option value="semanas">Próximas 8 semanas</option>
          </select>
          <select style={{ width: "auto" }} aria-label="Horizonte" value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            {[3, 6, 12, 24].map((m) => <option key={m} value={m}>{m} meses</option>)}
          </select>
        </div>
      </div>
      <label className="field check" style={{ margin: "6px 0 10px" }}>
        <input type="checkbox" checked={plans} onChange={(e) => setPlans(e.target.checked)} />
        <span>Incluir objetivos e investimentos planejados</span>
      </label>
      <Loading state={state}>{(data) => {
        const rows = view === "meses" ? data.meses : data.semanas;
        const labels = view === "meses" ? rows.map((r) => monthLabel(r.periodo)) : rows.map((r) => dateBR(r.inicio).slice(0, 5));
        return (
          <>
            {data.fica_negativo_em && <Status level="compromete">O saldo fica negativo em {dateBR(data.fica_negativo_em)} e chega a {money(data.menor_saldo)}.</Status>}
            <div className="tiles">
              <Tile label="Saldo hoje" value={money(data.saldo_atual)} />
              <Tile label="Menor saldo previsto" value={money(data.menor_saldo)} hint={`em ${dateBR(data.menor_saldo_em)}`} tone={data.menor_saldo < 0 ? "neg" : ""} />
            </div>
            <LineChart data={rows} labels={labels} height={180} series={[{ key: "saldo", label: "Saldo previsto", color: "var(--s1)" }]} />
            <h3>Entradas e saídas previstas</h3>
            <BarChart data={rows} labels={labels} height={170} series={[{ key: "entradas", label: "Entradas", color: "var(--s3)" }, { key: "saidas", label: "Saídas", color: "var(--s2)", down: true }]} />
            <p className="muted">Usa o que está lançado como previsto, as regras recorrentes, as dívidas e as parcelas. Lançamentos manuais do dia a dia só entram depois de registrados.</p>
            {data.proximos.length > 0 && (
              <Foldout label="Ver próximos itens">{() => (
                <div className="table-wrap"><table><tbody>
                  {data.proximos.map((e, i) => <tr key={i}><td>{dateBR(e.data)}</td><td>{e.descricao}</td><td className={`num ${e.valor > 0 ? "pos" : ""}`}>{money(e.valor)}</td></tr>)}
                </tbody></table></div>
              )}</Foldout>
            )}
          </>
        );
      }}</Loading>
    </section>
  );
}

export function Ceilings({ compact }) {
  const { period } = useApp();
  const state = useApi(`/orcamento/tetos${query({ ano: period.ano, mes: period.mes })}`);
  const categories = flatten(useApi("/contas/categorias").data || []);
  return (
    <section className="card">
      <h2>Tetos por categoria: {monthName(period.mes)}/{period.ano}</h2>
      <Loading state={state}>{(list) => (list.length ? list.map((c) => (
        <div key={c.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--grid)" }}>
          <div className="row between"><b>{c.categoria}{c.oculto ? " 🔒" : ""}</b><span className="pill">{LABEL[c.situacao]}</span></div>
          <p className="muted">{money(c.gasto)} de {money(c.teto)} · {c.disponivel >= 0 ? `sobram ${money(c.disponivel)}` : `passou ${money(-c.disponivel)}`}</p>
          <Progress value={c.percentual} tone={TONE[c.situacao]} />
          {!compact && (
            <div className="row" style={{ marginTop: 6 }}>
              <Foldout label="Alterar">{(close) => (
                <Form
                  resetOnSuccess={false} fields={[{ name: "limit_cents", type: "money", label: "Teto mensal", required: true, value: c.teto }]}
                  onSubmit={async (v) => { await api(`/orcamento/tetos/${c.id}`, { method: "PATCH", body: v }); close(); state.reload(); }}
                />
              )}</Foldout>
              <button type="button" className="small" onClick={async () => { await api(`/orcamento/tetos/${c.id}`, { method: "DELETE" }); state.reload(); }}>Remover</button>
            </div>
          )}
        </div>
      )) : <Empty>Nenhum teto definido.</Empty>)}</Loading>
      {!compact && (
        <div style={{ marginTop: 10 }}>
          <Foldout label="Novo teto">{(close) => (
            <Form
              fields={[
                { name: "category_id", type: "select", label: "Categoria", required: true, options: categories },
                { name: "limit_cents", type: "money", label: "Teto mensal", required: true },
                { name: "joint", type: "select", label: "Vale para", placeholder: false, value: "true", options: [{ value: "true", label: "O casal" }, { value: "false", label: "Só eu" }] },
                { name: "hidden", type: "check", label: "Ocultar da outra pessoa (só individual)" },
              ]}
              onSubmit={async (v) => {
                await api("/orcamento/tetos", { method: "POST", body: { ...v, category_id: Number(v.category_id), joint: v.joint === "true" } });
                close(); state.reload();
              }}
            />
          )}</Foldout>
        </div>
      )}
    </section>
  );
}

export default function Planejamento() {
  const { modules } = useApp();
  return (
    <>
      <h1>Planejamento</h1>
      {modules.includes("previsao") && <Forecast />}
      {modules.includes("orcamento") && <Ceilings />}
    </>
  );
}
