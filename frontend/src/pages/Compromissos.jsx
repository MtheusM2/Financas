import { useState } from "react";
import { api, useApi } from "../api";
import { dateBR, money, monthLabel, today } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Progress, Status } from "../ui";
import { accountOptions, flatten, useWritableAccounts } from "./Lancamentos";

const percent = (value) => Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 4 });
const hideField = { name: "hidden", type: "check", label: "Ocultar da outra pessoa" };

const dayOf = (iso) => Number(iso.slice(8, 10));
const tagId = (v) => (v.category_id ? Number(v.category_id) : null);
const repeatOptions = [
  { value: "mensal", label: "Todo mês, sem data para acabar" },
  { value: "parcelada", label: "Parcelada, com número de parcelas" },
];

function debtSituation(d) {
  if (d.situacao === "quitada") return "✓ Quitada";
  if (d.situacao === "em_dia") return "✓ Em dia";
  if (d.situacao === "atrasada") return `✕ Atrasada há ${-d.dias} dia(s)`;
  return d.dias === 0 ? "! Vence hoje" : `! Vence em ${d.dias} dia(s)`;
}

function DebtForm({ debt, accounts, tags, canHide = true, submit, onSubmit, secondary }) {
  const [repeat, setRepeat] = useState(debt?.total_parcelas ? "parcelada" : "mensal");
  return (
    <Form
      resetOnSuccess={false} submit={submit} secondary={secondary}
      initial={debt && {
        name: debt.nome, installment_cents: debt.parcela, due: debt.proximo_vencimento, repeat,
        total_installments: debt.total_parcelas, category_id: debt.categoria_id ? String(debt.categoria_id) : "", hidden: debt.oculta,
      }}
      onChange={(v) => setRepeat(v.repeat)}
      fields={[
        { name: "name", label: "Nome", required: true, max: 80 },
        { name: "installment_cents", type: "money", label: "Valor", required: true, help: "Se mudar todo mês, como luz, use o valor médio. Na hora de pagar você informa o real." },
        { name: "due", type: "date", label: "Próximo vencimento", required: true, help: "Depois repete nesse mesmo dia, todo mês." },
        { name: "repeat", type: "select", label: "Repetição", required: true, placeholder: false, value: "mensal", options: repeatOptions },
        repeat === "parcelada" && { name: "total_installments", type: "integer", label: "Total de parcelas", required: true, min: 1 },
        repeat === "parcelada" && !debt && { name: "paid_before", type: "integer", label: "Parcelas pagas antes de usar o sistema", min: 0, value: "0",
          help: "Só conta quantas faltam, não desconta do saldo. Para descontar um pagamento, deixe 0 e use Registrar pagamento depois de salvar." },
        { name: "category_id", type: "select", label: "Tag", options: tags, placeholder: "Sem tag", help: "Crie novas em Ajustes > Categorias e tags." },
        !debt && { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
        canHide && hideField,
      ]}
      onSubmit={onSubmit}
    />
  );
}

function PayDebt({ debt, onDone }) {
  const month = debt.proximo_vencimento.slice(0, 7);
  const label = debt.situacao === "em_dia" ? `Adiantar ${monthLabel(month)}` : `Registrar pagamento de ${monthLabel(month)}`;
  return (
    <Foldout label={label}>{(close) => (
      <Form
        submit="Confirmar pagamento"
        fields={[
          { name: "date", type: "date", label: "Pago em", required: true, help: "O valor sai do saldo no mês desta data." },
          { name: "amount_cents", type: "money", label: "Valor pago", required: true, value: debt.parcela },
        ]}
        onSubmit={async (v) => {
          await api(`/dividas/${debt.id}/pagar`, { method: "POST", body: v });
          close(); onDone(`Pagamento de ${money(v.amount_cents)} registrado em ${debt.nome}.`);
        }}
      />
    )}</Foldout>
  );
}

const paymentCount = (d) => d.parcelas_pagas - d.parcelas_ja_pagas;

function FixPaidBefore({ debt: d, onDone }) {
  return (
    <Foldout label="Corrigir parcelas pagas antes">{(close) => (
      <Form
        resetOnSuccess={false} submit="Salvar"
        fields={[{
          name: "paid_before", type: "integer", label: "Parcelas pagas antes de usar o sistema", required: true, min: 0,
          value: String(d.parcelas_ja_pagas),
          help: "Elas não saem do saldo. Se alguma foi paga agora, diminua aqui e depois toque em Registrar pagamento.",
        }]}
        onSubmit={async (v) => {
          await api(`/dividas/${d.id}`, { method: "PATCH", body: { paid_before: v.paid_before } });
          close(); onDone(`${d.nome} corrigida. Agora registre o pagamento para ele sair do saldo.`);
        }}
      />
    )}</Foldout>
  );
}


function DebtCard({ debt: d, tags, onDone, selected, onSelect }) {
  const { user } = useApp();
  const run = async (question, action, message) => {
    if (!window.confirm(question)) return;
    try {
      await action();
      onDone(message);
    } catch (error) {
      window.alert(error.message);
    }
  };
  const hasPayment = d.ultimo_pagamento !== null;
  const undo = () => run(
    `Desfazer o pagamento de ${money(d.ultimo_pagamento.valor)} de ${dateBR(d.ultimo_pagamento.data)}? O lançamento será excluído.`,
    () => api(`/dividas/${d.id}/pagamentos/ultimo`, { method: "DELETE" }), `Pagamento desfeito em ${d.nome}.`,
  );
  const setActive = (active) => run(
    active ? `Reativar ${d.nome}?` : `Encerrar ${d.nome}? Ela sai dos avisos e da previsão, e os pagamentos continuam no histórico.`,
    () => api(`/dividas/${d.id}`, { method: "PATCH", body: { active } }), `${d.nome} ${active ? "reativada" : "encerrada"}.`,
  );
  const remove = () => run(
    hasPayment
      ? `Excluir ${d.nome} e ${paymentCount(d)} pagamento(s) registrado(s)? Isso não pode ser desfeito. Para manter o histórico, use Encerrar.`
      : `Excluir ${d.nome}? Isso não pode ser desfeito.`,
    () => api(`/dividas/${d.id}`, { method: "DELETE" }), `${d.nome} excluída.`,
  );
  return (
    <div className="card">
      <div className="row between">
        <span className="row">
          <input type="checkbox" aria-label={`Selecionar ${d.nome}`} checked={selected} onChange={() => onSelect(d.id)} />
          <span><b>{d.nome}{d.oculta ? " 🔒" : ""}</b>{d.categoria && <span className="pill" style={{ marginLeft: 6 }}>{d.categoria}</span>}</span>
        </span>
        {d.ativa ? <span className={`pill ${d.situacao}`}>{debtSituation(d)}</span> : <span className="pill">Encerrada</span>}
      </div>
      <p className="muted" style={{ marginTop: 4 }}>
        {money(d.parcela)} todo dia {d.vencimento}
        {d.total_parcelas ? ` · ${d.parcelas_pagas} de ${d.total_parcelas} parcelas · faltam ${money(d.saldo_restante)}` : " · sem data para acabar"}
      </p>
      {d.ativa && !d.quitada && (
        <p className="muted">
          Próximo vencimento: <b>{dateBR(d.proximo_vencimento)}</b>
          {d.atrasadas > 1 ? ` · ${d.atrasadas} pagamentos em aberto` : ""}
          {hasPayment ? ` · último pagamento: ${money(d.ultimo_pagamento.valor)} em ${dateBR(d.ultimo_pagamento.data)}` : ""}
        </p>
      )}
      {d.quitada && paymentCount(d) === 0 && (
        <Status level="atencao">
          Marcada como quitada só por "parcelas pagas antes", sem nenhum pagamento registrado: nenhum valor saiu do saldo.
          Se o pagamento foi feito agora, toque em Corrigir parcelas pagas antes, diminua o número e depois use Registrar pagamento.
        </Status>
      )}
      {d.total_parcelas && <Progress value={(d.parcelas_pagas / d.total_parcelas) * 100} />}
      <div className="row" style={{ marginTop: 8 }}>
        {d.ativa && !d.quitada && <PayDebt debt={d} onDone={onDone} />}
        {d.ativa && !d.quitada && (
          <Foldout label="Editar">{(close) => (
            <DebtForm
              debt={d} tags={tags} canHide={user.id === d.pessoa_id} submit="Salvar alterações"
              onSubmit={async ({ name, installment_cents, due, repeat, total_installments, category_id, hidden }) => {
                await api(`/dividas/${d.id}`, { method: "PATCH", body: {
                  name, installment_cents, next_due: due, category_id: tagId({ category_id }),
                  total_installments: repeat === "parcelada" ? total_installments : null,
                  ...(user.id === d.pessoa_id ? { hidden } : {}),
                } });
                close(); onDone(`${name} atualizada.`);
              }}
            />
          )}</Foldout>
        )}
        {d.ativa && d.parcelas_ja_pagas > 0 && <FixPaidBefore debt={d} onDone={onDone} />}
        {hasPayment && <button type="button" className="small" onClick={undo}>Desfazer último pagamento</button>}
        {!d.ativa && <button type="button" className="small" onClick={() => setActive(true)}>Reativar</button>}
        {d.ativa && !d.quitada && <button type="button" className="small" onClick={() => setActive(false)}>Encerrar</button>}
        <button type="button" className="small" onClick={remove}>Excluir</button>
      </div>
    </div>
  );
}

function Debts({ accounts }) {
  const state = useApi("/dividas");
  const categories = useApi("/contas/categorias");
  const tags = flatten(categories.data || []);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState([]);
  const done = (text) => { setMessage(text); setSelected([]); state.reload(); };
  const toggle = (id) => setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  const removeSelected = async (list) => {
    const chosen = list.filter((d) => selected.includes(d.id));
    const payments = chosen.reduce((sum, d) => sum + paymentCount(d), 0);
    const extra = payments ? ` e ${payments} pagamento(s) registrado(s)` : "";
    if (!window.confirm(`Excluir ${chosen.length} dívida(s)${extra}? Isso não pode ser desfeito.`)) return;
    try {
      await api("/dividas/excluir", { method: "POST", body: { ids: chosen.map((d) => d.id) } });
      done(`${chosen.length} dívida(s) excluída(s).`);
    } catch (error) {
      window.alert(error.message);
    }
  };
  return (
    <section className="card">
      <h2>Dívidas e contas fixas</h2>
      <p className="muted">Nada sai do saldo sozinho. A conta entra na previsão, avisa 7 dias antes de vencer e só é descontada quando você registra o pagamento.</p>
      {message && <Status level="feito">{message}</Status>}
      <Loading state={state}>{(list) => {
        const open = list.filter((d) => d.ativa);
        const closed = list.filter((d) => !d.ativa);
        return (
          <>
            {list.length > 0 && (
              <div className="bulk-bar">
                <label className="field check">
                  <input type="checkbox" checked={selected.length === list.length} onChange={() => setSelected(selected.length === list.length ? [] : list.map((d) => d.id))} />
                  <span>Selecionar todas</span>
                </label>
                {selected.length > 0 && <button type="button" className="small" onClick={() => removeSelected(list)}>Excluir selecionadas ({selected.length})</button>}
              </div>
            )}
            {open.length ? open.map((d) => <DebtCard key={d.id} debt={d} tags={tags} onDone={done} selected={selected.includes(d.id)} onSelect={toggle} />) : <Empty>Nenhuma dívida ativa.</Empty>}
            {closed.length > 0 && (
              <div style={{ marginBottom: 10 }}>
                <Foldout label={`Encerradas (${closed.length})`}>{() => closed.map((d) => <DebtCard key={d.id} debt={d} tags={tags} onDone={done} selected={selected.includes(d.id)} onSelect={toggle} />)}</Foldout>
              </div>
            )}
          </>
        );
      }}</Loading>
      <Foldout label="Nova dívida">{(close) => (
        <DebtForm
          accounts={accounts} tags={tags}
          onSubmit={async ({ due, repeat, ...v }) => {
            await api("/dividas", { method: "POST", body: {
              ...v, account_id: Number(v.account_id), category_id: tagId(v), due_day: dayOf(due), start_date: due,
              total_installments: repeat === "parcelada" ? v.total_installments : null, paid_before: v.paid_before || 0,
            } });
            close(); done(`${v.name} cadastrada.`);
          }}
        />
      )}</Foldout>
    </section>
  );
}

function Simulator({ item }) {
  const [result, setResult] = useState(null);
  return (
    <div>
      <Form
        resetOnSuccess={false} submit="Simular"
        fields={[
          { name: "amount_cents", type: "money", label: "Amortização extra", required: true },
          { name: "keep_term", type: "select", label: "Depois da amortização", placeholder: false, value: "false",
            options: [{ value: "false", label: "Reduzir o prazo" }, { value: "true", label: "Reduzir a parcela" }] },
        ]}
        onSubmit={async (v) => setResult(await api(`/financiamentos/${item.id}/simular`, { method: "POST", body: { ...v, keep_term: v.keep_term === "true" } }))}
      />
      {result && (
        <p style={{ marginTop: 8 }}>
          Economia de <b>{money(result.juros_economizados)}</b> em juros
          {result.meses_a_menos > 0 ? ` e ${result.meses_a_menos} mês(es) a menos` : ""}. Nada foi gravado.
        </p>
      )}
    </div>
  );
}

function Installments({ id }) {
  const state = useApi(`/financiamentos/${id}/parcelas`);
  return (
    <Loading state={state}>{(rows) => (
      <div className="table-wrap" style={{ maxHeight: 340, overflowY: "auto" }}><table>
        <thead><tr><th>Nº</th><th>Mês</th><th className="num">Parcela</th><th className="num">Juros</th><th className="num">Amortização</th><th className="num">Taxas</th><th className="num">Saldo</th><th /></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.numero}>
            <td>{r.numero}</td><td>{monthLabel(r.mes)}</td><td className="num">{money(r.parcela)}</td><td className="num">{money(r.juros)}</td>
            <td className="num">{money(r.amortizacao + r.extra)}</td><td className="num">{money(r.taxa)}</td><td className="num">{money(r.saldo)}</td>
            <td>{r.paga ? "✓ paga" : ""}</td>
          </tr>
        ))}</tbody>
      </table></div>
    )}</Loading>
  );
}

function Financings({ accounts }) {
  const state = useApi("/financiamentos");
  return (
    <section className="card">
      <h2>Financiamentos</h2>
      <Loading state={state}>{(list) => (list.length ? list.map((f) => (
        <div key={f.id} className="card stack">
          <div className="row between">
            <span><b>{f.nome}{f.oculta ? " 🔒" : ""}</b><span className="pill" style={{ marginLeft: 6 }}>{f.sistema === "PRICE" ? "Price" : "SAC"}</span></span>
            <span className={`pill ${f.situacao}`}>{debtSituation(f)}</span>
          </div>
          {!f.quitado && (
            <p className="muted">
              Próximo vencimento: <b>{dateBR(f.proximo_vencimento)}</b>{f.atrasadas > 1 ? ` · ${f.atrasadas} parcelas em aberto` : ""}
            </p>
          )}
          <div className="tiles" style={{ marginBottom: 0 }}>
            <div><div className="muted">Valor do bem</div>{money(f.valor_bem)}</div>
            <div><div className="muted">Entrada</div>{money(f.entrada)}</div>
            <div><div className="muted">Financiado</div>{money(f.valor_financiado)}</div>
            <div><div className="muted">Juros</div>{percent(f.juros_ano)}% a.a. ({percent(f.juros_mes)}% a.m.)</div>
            <div><div className="muted">Parcelas</div>{f.parcelas_pagas} de {f.parcelas} (faltam {f.parcelas_restantes})</div>
            <div><div className="muted">Próxima parcela</div>{money(f.proxima_parcela)}</div>
            <div><div className="muted">Saldo devedor</div><b>{money(f.saldo_devedor)}</b></div>
            <div><div className="muted">Juros totais</div>{money(f.juros_total)}</div>
            <div><div className="muted">Total a pagar</div>{money(f.total_pago)}</div>
            <div><div className="muted">Primeiro vencimento</div>{dateBR(f.primeiro_vencimento)}</div>
          </div>
          <Progress value={(f.parcelas_pagas / Math.max(f.parcelas, 1)) * 100} />
          <div className="row">
            {!f.quitado && <button type="button" className="small" onClick={async () => {
              if (!window.confirm(`Registrar o pagamento de ${money(f.proxima_parcela)} de ${f.nome} com a data de hoje?`)) return;
              try {
                await api(`/financiamentos/${f.id}/pagar`, { method: "POST", body: { date: today() } });
                state.reload();
              } catch (error) {
                window.alert(error.message);
              }
            }}>Registrar parcela</button>}
            <button type="button" className="small" onClick={async () => {
              if (!window.confirm(`Excluir ${f.nome} e os pagamentos registrados dele? Isso não pode ser desfeito.`)) return;
              try {
                await api(`/financiamentos/${f.id}`, { method: "DELETE" });
                state.reload();
              } catch (error) {
                window.alert(error.message);
              }
            }}>Excluir</button>
            <Foldout label="Ver todas as parcelas">{() => <Installments id={f.id} />}</Foldout>
            <Foldout label="Simular amortização">{() => <Simulator item={f} />}</Foldout>
            <Foldout label="Registrar amortização">{(close) => (
              <Form
                submit="Registrar"
                fields={[
                  { name: "amount_cents", type: "money", label: "Valor", required: true },
                  { name: "date", type: "date", label: "Data", required: true },
                  { name: "keep_term", type: "select", label: "Depois da amortização", placeholder: false, value: "false",
                    options: [{ value: "false", label: "Reduzir o prazo" }, { value: "true", label: "Reduzir a parcela" }] },
                ]}
                onSubmit={async (v) => {
                  await api(`/financiamentos/${f.id}/amortizar`, { method: "POST", body: { ...v, keep_term: v.keep_term === "true" } });
                  close(); state.reload();
                }}
              />
            )}</Foldout>
          </div>
        </div>
      )) : <Empty>Nenhum financiamento cadastrado.</Empty>)}</Loading>
      <Foldout label="Novo financiamento">{(close) => (
        <Form
          fields={[
            { name: "name", label: "Nome", required: true, max: 80 },
            { name: "asset_value_cents", type: "money", label: "Valor do bem", required: true },
            { name: "down_payment_cents", type: "money", label: "Entrada" },
            { name: "annual_rate_percent", type: "percent", label: "Juros ao ano (%)", required: true },
            { name: "system", type: "select", label: "Sistema", required: true, placeholder: false, value: "PRICE", options: [{ value: "PRICE", label: "Price (parcela fixa)" }, { value: "SAC", label: "SAC (parcela decrescente)" }] },
            { name: "term_months", type: "integer", label: "Prazo em meses", required: true, min: 1, maxValue: 600 },
            { name: "monthly_fee_cents", type: "money", label: "Seguro e taxas por mês" },
            { name: "first_due", type: "date", label: "Primeiro vencimento", required: true },
            { name: "paid_before", type: "integer", label: "Parcelas pagas antes de usar o sistema", min: 0, value: "0",
              help: "Só conta quantas faltam, não desconta do saldo." },
            { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
            hideField,
          ]}
          onSubmit={async (v) => {
            await api("/financiamentos", { method: "POST", body: {
              ...v, account_id: Number(v.account_id), down_payment_cents: v.down_payment_cents || 0,
              monthly_fee_cents: v.monthly_fee_cents || 0, paid_before: v.paid_before || 0,
            } });
            close(); state.reload();
          }}
        />
      )}</Foldout>
    </section>
  );
}

export default function Compromissos() {
  const { modules } = useApp();
  const accounts = useWritableAccounts();
  return (
    <>
      <h1>Dívidas e financiamentos</h1>
      {modules.includes("dividas") && <Debts accounts={accounts} />}
      {modules.includes("financiamentos") && <Financings accounts={accounts} />}
    </>
  );
}
