import { useState } from "react";
import { api, query, useApi } from "../api";
import { money, parseMoney, today } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Progress, Status } from "../ui";
import Avaliacao from "./Avaliacao";
import { accountOptions, useWritableAccounts } from "./Lancamentos";

const METRICS = { guardar: "Guardar um valor", investir: "Ter um valor investido", livre: "Personalizado" };

function ChallengeCard({ item, accounts, onChange }) {
  const post = async (path, body) => { await api(`/desafios/${item.id}/${path}`, { method: "POST", body }); onChange(); };
  return (
    <div className="card">
      <div className="row between"><b>{item.nome}{item.oculto ? " 🔒" : ""}</b><span className="pill">{item.conjunto ? "Em conjunto" : "Individual"} · {item.situacao === "concluido" ? "✓ Concluído" : item.situacao === "cancelado" ? "Cancelado" : "Em andamento"}</span></div>
      <p className="muted">{METRICS[item.metrica]}: {money(item.progresso)} de {money(item.meta)} ({item.percentual}%) · Multiplicador {item.multiplicador}x</p>
      <Progress value={item.percentual} />
      <p style={{ marginTop: 6 }}>Recompensa: <b>{money(item.liberado)}</b> para {item.recompensa_rotulo}; {money(item.continua_guardado)} continuam guardados.</p>
      {item.situacao === "ativo" && (
        <div className="row">
          {item.metrica === "guardar" && (
            <Foldout label="Aportar">{(close) => (
              <Form
                submit="Registrar"
                fields={[
                  { name: "amount_cents", type: "money", label: "Valor", required: true },
                  { name: "date", type: "date", label: "Data", required: true },
                  { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
                ]}
                onSubmit={async (v) => { await post("aportar", { ...v, account_id: Number(v.account_id) }); close(); }}
              />
            )}</Foldout>
          )}
          {item.metrica === "livre" && (
            <Foldout label="Informar progresso">{(close) => (
              <Form
                resetOnSuccess={false} fields={[{ name: "manual_progress_cents", type: "money", label: "Progresso atual", required: true }]}
                onSubmit={async (v) => { await api(`/desafios/${item.id}`, { method: "PATCH", body: v }); close(); onChange(); }}
              />
            )}</Foldout>
          )}
          {item.alcancado && <button type="button" className="small primary" onClick={() => post("concluir")}>Concluir desafio</button>}
          <button type="button" className="small" onClick={async () => {
            if (!window.confirm("Cancelar este desafio?")) return;
            await api(`/desafios/${item.id}`, { method: "PATCH", body: { status: "cancelado" } });
            onChange();
          }}>Cancelar</button>
        </div>
      )}
      {item.situacao === "concluido" && !item.recompensa_usada && (
        <Foldout label="Usar recompensa">{(close) => (
          <Form
            submit="Lançar como lazer"
            fields={[
              { name: "date", type: "date", label: "Data", required: true },
              { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
              { name: "description", label: "Descrição", max: 160 },
            ]}
            onSubmit={async (v) => { await post("usar-recompensa", { ...v, account_id: Number(v.account_id) }); close(); }}
          />
        )}</Foldout>
      )}
      {item.recompensa_usada && <p className="muted">✓ Recompensa usada.</p>}
    </div>
  );
}

export default function Desafios() {
  const { scope } = useApp();
  const accounts = useWritableAccounts();
  const state = useApi("/desafios");
  const [draft, setDraft] = useState({ multiplier: "5" });
  const reward = parseMoney(draft.reward_cents);
  const multiplier = String(draft.multiplier || "5").replace(",", ".");
  const validMultiplier = /^\d+(\.\d+)?$/.test(multiplier) && Number(multiplier) > 0 ? multiplier : "5";
  const suggestion = useApi(`/desafios/sugestao${query({ recompensa: reward > 0 ? reward : undefined, multiplicador: validMultiplier, escopo: scope })}`);
  const [assessment, setAssessment] = useState(null);

  const s = suggestion.data;
  const target = parseMoney(draft.target_cents) || (reward > 0 ? Math.round(reward * Number(validMultiplier)) : 0);
  const months = Number(draft.term_months) || s?.prazo_meses;

  return (
    <>
      <h1>Desafios do casal</h1>
      <section className="card">
        <Loading state={state}>{(list) => (list.length
          ? list.map((c) => <ChallengeCard key={c.id} item={c} accounts={accounts} onChange={state.reload} />)
          : <Empty>Nenhum desafio ainda. Proponham o primeiro abaixo.</Empty>)}</Loading>
      </section>

      <section className="card">
        <h2>Novo desafio</h2>
        <p className="muted">Quanto vocês querem gastar? A meta é esse valor multiplicado. Ao concluir, a recompensa é liberada e o restante continua guardado.</p>
        {s && (s.tem_sobra ? (
          <Status level="info">
            <b>Sugestão:</b> recompensa de {money(s.recompensa)} × {Number(s.multiplicador)} = meta de {money(s.meta)},
            em {s.prazo_meses} mês(es), guardando {money(s.aporte_mensal)} por mês. Base: {money(s.sobra_media)} livres por mês.
          </Status>
        ) : (
          <Status level="compromete">Hoje não há folga no orçamento para um desafio novo. Vocês podem criar mesmo assim, mas ele comprometeria as contas.</Status>
        ))}
        <Form
          submit="Criar desafio"
          fields={[
            { name: "name", label: "Nome do desafio", required: true, max: 80 },
            { name: "reward_cents", type: "money", label: "Quanto quer gastar", required: true },
            { name: "reward_label", label: "Com o quê", required: true, max: 80, value: "Lazer", placeholder: "Lazer, hobby, desejo…" },
            { name: "multiplier", type: "percent", label: "Multiplicador", value: "5" },
            { name: "target_cents", type: "money", label: "Meta personalizada", help: "Opcional. Exemplo: 10.000,00 substitui o multiplicador." },
            { name: "metric", type: "select", label: "Como medir", placeholder: false, value: "guardar", options: Object.entries(METRICS).map(([value, label]) => ({ value, label })) },
            { name: "term_months", type: "integer", label: "Prazo em meses", min: 1, maxValue: 600, help: "Vazio: usa a sugestão." },
            { name: "start_date", type: "date", label: "Início", required: true, value: today() },
            { name: "joint", type: "select", label: "Para quem", placeholder: false, value: "true", options: [{ value: "true", label: "Para os dois" }, { value: "false", label: "Só para mim" }] },
            { name: "hidden", type: "check", label: "Ocultar da outra pessoa (só individual)" },
          ]}
          onChange={(values) => { setDraft(values); setAssessment(null); }}
          onSubmit={async (v) => {
            await api("/desafios", { method: "POST", body: {
              name: v.name, reward_cents: v.reward_cents, reward_label: v.reward_label, metric: v.metric,
              multiplier: Number(v.multiplier) > 0 ? v.multiplier : "5", target_cents: v.target_cents,
              term_months: v.term_months || s?.prazo_meses || null, start_date: v.start_date,
              joint: v.joint === "true", hidden: v.hidden,
            } });
            setAssessment(null);
            state.reload();
            suggestion.reload();
          }}
          secondary={(
            <button type="button" disabled={!target || !months} onClick={async () => {
              setAssessment(await api("/orcamento/avaliar", { method: "POST", body: { target_cents: target, term_months: months, escopo: scope } }));
            }}>Avaliar no orçamento</button>
          )}
        >
          <Avaliacao result={assessment} />
        </Form>
      </section>
    </>
  );
}
