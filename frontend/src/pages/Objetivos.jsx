import { useState } from "react";
import { api, useApi } from "../api";
import { LineChart } from "../charts";
import { money, monthLabel, parseMoney, today } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Progress } from "../ui";
import Avaliacao from "./Avaliacao";
import { accountOptions, useWritableAccounts } from "./Lancamentos";

const STATUS = { concluido: "✓ Concluído", no_ritmo: "✓ No ritmo", atrasado: "! Atrasado", sem_plano: "Sem plano" };

function Schedule({ id }) {
  const state = useApi(`/objetivos/${id}/cronograma`);
  return (
    <Loading state={state}>{(rows) => (
      <LineChart
        data={rows} labels={rows.map((r) => monthLabel(r.mes))}
        series={[{ key: "previsto", label: "Previsto", color: "var(--s1)" }, { key: "realizado", label: "Realizado", color: "var(--s2)" }]}
      />
    )}</Loading>
  );
}

function GoalCard({ goal, accounts, users, onChange }) {
  const name = (id) => users.find((u) => String(u.id) === String(id))?.nome || "—";
  return (
    <div className="card">
      <div className="row between"><b>{goal.nome}{goal.oculto ? " 🔒" : ""}</b><span className="pill">{goal.conjunto ? "Em conjunto" : "Individual"} · {STATUS[goal.situacao]}</span></div>
      <p className="muted">
        {money(goal.guardado)} de {money(goal.valor_objetivo)} ({goal.percentual}%) · Plano de {money(goal.aporte_plano)}/mês
        {goal.data_prevista ? ` · Previsão ${monthLabel(goal.data_prevista)}` : ""}
      </p>
      <Progress value={goal.percentual} />
      {goal.folga_mensal !== null && goal.folga_mensal < 0 && <p className="neg" style={{ marginTop: 6 }}>Para cumprir o prazo, faltam {money(-goal.folga_mensal)} por mês.</p>}
      {Object.keys(goal.por_pessoa).length > 0 && (
        <p className="muted" style={{ marginTop: 6 }}>
          {goal.conjunto ? "Quanto cada um investiu" : "Aportado"}: {Object.entries(goal.por_pessoa).map(([id, v]) => `${name(id)} ${money(v)}${goal.conjunto && goal.divisao[id] !== undefined ? ` (${goal.divisao[id]}%)` : ""}`).join(" · ")}
          {goal.conjunto && goal.valor_inicial > 0 ? ` · Os ${money(goal.valor_inicial)} já guardados no início não entram na divisão.` : ""}
        </p>
      )}
      <div className="row" style={{ marginTop: 8 }}>
        <Foldout label="Aportar">{(close) => (
          <Form
            submit="Registrar aporte"
            fields={[
              { name: "amount_cents", type: "money", label: "Valor", required: true },
              { name: "date", type: "date", label: "Data", required: true },
              { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
            ]}
            onSubmit={async (v) => { await api(`/objetivos/${goal.id}/aportar`, { method: "POST", body: { ...v, account_id: Number(v.account_id) } }); close(); onChange(); }}
          />
        )}</Foldout>
        <Foldout label="Ver cronograma">{() => <Schedule id={goal.id} />}</Foldout>
        <Foldout label="Alterar">{(close) => (
          <Form
            resetOnSuccess={false}
            fields={[
              { name: "target_cents", type: "money", label: "Valor do objetivo", required: true, value: goal.valor_objetivo },
              { name: "term_months", type: "integer", label: "Prazo em meses", min: 1, maxValue: 600, value: goal.prazo },
              { name: "monthly_cents", type: "money", label: "Aporte mensal", value: goal.aporte_mensal },
            ]}
            onSubmit={async (v) => { await api(`/objetivos/${goal.id}`, { method: "PATCH", body: v }); close(); onChange(); }}
          />
        )}</Foldout>
      </div>
    </div>
  );
}

export default function Objetivos() {
  const { scope, users } = useApp();
  const accounts = useWritableAccounts();
  const state = useApi("/objetivos");
  const [draft, setDraft] = useState({});
  const onlyMine = draft.joint === "false";
  const [assessment, setAssessment] = useState(null);
  const [failure, setFailure] = useState(null);

  const evaluate = async () => {
    setFailure(null);
    const target = parseMoney(draft.target_cents);
    const saved = parseMoney(draft.initial_cents) || 0;
    const monthly = parseMoney(draft.monthly_cents) || null;
    let term = Number(draft.term_months) || 0;
    if (!term && monthly && target) term = Math.ceil(Math.max(target - saved, 0) / monthly) || 1;
    if (!target || !term) { setFailure("Informe o valor do objetivo e o prazo ou o aporte mensal."); return; }
    try {
      setAssessment(await api("/orcamento/avaliar", { method: "POST", body: {
        target_cents: target, saved_cents: saved, term_months: term, monthly_cents: monthly,
        invest_rate_percent: String(draft.monthly_rate_percent || "0").replace(",", "."), escopo: scope,
      } }));
    } catch (error) { setFailure(error.message); }
  };

  return (
    <>
      <h1>Objetivos</h1>
      <section className="card">
        <Loading state={state}>{(list) => (list.length
          ? list.map((g) => <GoalCard key={g.id} goal={g} accounts={accounts} users={users} onChange={state.reload} />)
          : <Empty>Nenhum objetivo ainda. Crie o primeiro abaixo.</Empty>)}</Loading>
      </section>
      <section className="card">
        <h2>Novo objetivo</h2>
        <p className="muted">Informe o prazo, o aporte mensal ou os dois. Antes de salvar, confira se cabe no orçamento. Nos objetivos em conjunto, a parte de cada um é calculada sozinha pelos aportes que cada pessoa registrar.</p>
        <Form
          key={users.length} submit="Salvar objetivo"
          fields={[
            { name: "name", label: "Nome", required: true, max: 80, placeholder: "Viagem, entrada do imóvel…" },
            { name: "target_cents", type: "money", label: "Valor do objetivo", required: true },
            { name: "initial_cents", type: "money", label: "Já guardado" },
            { name: "start_date", type: "date", label: "Início", required: true, value: today() },
            { name: "term_months", type: "integer", label: "Prazo em meses", min: 1, maxValue: 600 },
            { name: "monthly_cents", type: "money", label: "Aporte mensal" },
            { name: "monthly_rate_percent", type: "percent", label: "Rendimento ao mês (%)", help: "Opcional. Vazio considera zero." },
            { name: "joint", type: "select", label: "De quem é", placeholder: false, value: "true", options: [{ value: "true", label: "Em conjunto" }, { value: "false", label: "Só meu" }] },
            onlyMine && { name: "hidden", type: "check", label: "Ocultar da outra pessoa" },
          ]}
          onChange={(values) => { setDraft(values); setAssessment(null); }}
          onSubmit={async (v) => {
            if (!v.term_months && !v.monthly_cents) throw new Error("Informe o prazo ou o aporte mensal.");
            await api("/objetivos", { method: "POST", body: {
              name: v.name, target_cents: v.target_cents, initial_cents: v.initial_cents || 0, start_date: v.start_date,
              term_months: v.term_months, monthly_cents: v.monthly_cents, monthly_rate_percent: v.monthly_rate_percent,
              joint: v.joint === "true", hidden: v.joint === "false" && !!v.hidden,
            } });
            setAssessment(null);
            setDraft({});
            state.reload();
          }}
          secondary={<button type="button" onClick={evaluate}>Avaliar no orçamento</button>}
        >
          {failure && <div className="error-box" role="alert">{failure}</div>}
          <Avaliacao result={assessment} />
        </Form>
      </section>
    </>
  );
}
