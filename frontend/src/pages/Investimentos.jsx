import { api, useApi } from "../api";
import { dateBR, money } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Progress, ResultValue, Tile } from "../ui";
import { accountOptions, useWritableAccounts } from "./Lancamentos";

function Investments({ accounts }) {
  const state = useApi("/investimentos");
  return (
    <section className="card">
      <h2>Investimentos</h2>
      <Loading state={state}>{(list) => (list.length ? (
        <>
          <div className="tiles">
            <Tile label="Total aportado" value={money(list.reduce((t, i) => t + i.aportado, 0))} />
            <Tile label="Valor atual" value={money(list.reduce((t, i) => t + i.valor_atual, 0))} />
            <Tile label="Resultado" value={<ResultValue value={list.reduce((t, i) => t + i.resultado, 0)} />} />
            <Tile label="Aporte mensal planejado" value={money(list.filter((i) => i.ativo).reduce((t, i) => t + i.aporte_mensal, 0))} />
          </div>
          {list.map((i) => (
            <div key={i.id} className="card">
              <div className="row between"><b>{i.nome}{i.oculto ? " 🔒" : ""}</b><ResultValue value={i.resultado} /></div>
              <p className="muted">
                {i.categoria ? `${i.categoria} · ` : ""}Aportado {money(i.aportado)} · Atual {money(i.valor_atual)} · Plano {money(i.aporte_mensal)}/mês · Valor informado em {dateBR(i.valor_atualizado_em)}
              </p>
              <div className="row">
                <Foldout label="Aportar">{(close) => (
                  <Form
                    submit="Registrar aporte"
                    fields={[{ name: "amount_cents", type: "money", label: "Valor", required: true }, { name: "date", type: "date", label: "Data", required: true }]}
                    onSubmit={async (v) => { await api(`/investimentos/${i.id}/aportar`, { method: "POST", body: v }); close(); state.reload(); }}
                  />
                )}</Foldout>
                <Foldout label="Atualizar">{(close) => (
                  <Form
                    resetOnSuccess={false}
                    fields={[
                      { name: "current_value_cents", type: "money", label: "Valor atual", value: i.valor_atual },
                      { name: "monthly_plan_cents", type: "money", label: "Aporte mensal planejado", value: i.aporte_mensal },
                    ]}
                    onSubmit={async (v) => {
                      await api(`/investimentos/${i.id}`, { method: "PATCH", body: { current_value_cents: v.current_value_cents ?? 0, monthly_plan_cents: v.monthly_plan_cents ?? 0 } });
                      close(); state.reload();
                    }}
                  />
                )}</Foldout>
              </div>
            </div>
          ))}
        </>
      ) : <Empty>Nenhum investimento cadastrado.</Empty>)}</Loading>
      <Foldout label="Novo investimento">{(close) => (
        <Form
          fields={[
            { name: "name", label: "Nome", required: true, max: 80 },
            { name: "category", label: "Tipo", max: 60, placeholder: "Renda fixa, ações…" },
            { name: "initial_contributed_cents", type: "money", label: "Já aportado" },
            { name: "current_value_cents", type: "money", label: "Valor atual", help: "Vazio: igual ao já aportado." },
            { name: "monthly_plan_cents", type: "money", label: "Aporte mensal planejado" },
            { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
            { name: "hidden", type: "check", label: "Ocultar da outra pessoa" },
          ]}
          onSubmit={async (v) => {
            await api("/investimentos", { method: "POST", body: {
              ...v, account_id: Number(v.account_id), initial_contributed_cents: v.initial_contributed_cents || 0, monthly_plan_cents: v.monthly_plan_cents || 0,
            } });
            close(); state.reload();
          }}
        />
      )}</Foldout>
      <p className="muted" style={{ marginTop: 10 }}>O valor atual é informado por vocês; o sistema não consulta cotações.</p>
    </section>
  );
}

function Reserve({ accounts }) {
  const state = useApi("/reserva");
  return (
    <section className="card">
      <h2>Reserva de emergência</h2>
      {state.data === undefined ? <p className="muted">Carregando…</p> : state.data === null ? <Empty>Defina a meta para começar.</Empty> : (
        <>
          <div className="tiles">
            <Tile label="Guardado" value={money(state.data.guardado)} hint={`${state.data.percentual}% da meta`} />
            <Tile label="Meta" value={money(state.data.valor_objetivo)} hint={`${state.data.meses_meta} meses`} />
            <Tile label="Gasto essencial por mês" value={money(state.data.gasto_essencial_mensal)} />
            <Tile label="Meses cobertos" value={state.data.meses_cobertos ?? "—"} />
          </div>
          <Progress value={state.data.percentual} />
          <div style={{ marginTop: 10 }}>
            <Foldout label="Guardar na reserva">{(close) => (
              <Form
                submit="Registrar"
                fields={[
                  { name: "amount_cents", type: "money", label: "Valor", required: true },
                  { name: "date", type: "date", label: "Data", required: true },
                  { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
                ]}
                onSubmit={async (v) => { await api("/reserva/aportar", { method: "POST", body: { ...v, account_id: Number(v.account_id) } }); close(); state.reload(); }}
              />
            )}</Foldout>
          </div>
        </>
      )}
      <div style={{ marginTop: 10 }}>
        <Foldout label={state.data ? "Alterar meta" : "Definir meta"}>{(close) => (
          <Form
            resetOnSuccess={false}
            fields={[
              { name: "target_months", type: "integer", label: "Meses de gastos a cobrir", required: true, min: 1, maxValue: 60, value: state.data?.meses_meta ?? 6 },
              { name: "initial_cents", type: "money", label: "Já guardado antes", value: state.data?.valor_inicial },
              { name: "monthly_cents", type: "money", label: "Aporte mensal", value: state.data?.aporte_mensal },
              { name: "manual_target_cents", type: "money", label: "Meta em reais", help: "Vazio: calcula pelos gastos essenciais registrados." },
            ]}
            onSubmit={async (v) => {
              await api("/reserva", { method: "PUT", body: { ...v, initial_cents: v.initial_cents || 0 } });
              close(); state.reload();
            }}
          />
        )}</Foldout>
      </div>
    </section>
  );
}

export default function Investimentos() {
  const { modules } = useApp();
  const accounts = useWritableAccounts();
  return (
    <>
      <h1>Investimentos e reserva</h1>
      {modules.includes("reserva") && <Reserve accounts={accounts} />}
      {modules.includes("investimentos") && <Investments accounts={accounts} />}
    </>
  );
}
