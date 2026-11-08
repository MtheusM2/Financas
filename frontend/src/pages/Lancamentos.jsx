import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, query, useApi } from "../api";
import { dateBR, KINDS, money, parseMoney, today } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, ResultValue, Status } from "../ui";

const kindOptions = Object.entries(KINDS).map(([value, label]) => ({ value, label }));

export function flatten(tree, prefix = "") {
  return tree.flatMap((c) => [{ value: String(c.id), label: prefix + c.nome }, ...flatten(c.filhas, `${prefix}${c.nome} › `)]);
}

export function accountOptions(accounts) {
  return accounts.map((a) => ({ value: String(a.id), label: a.nome }));
}

export function useWritableAccounts() {
  const { accounts, user } = useApp();
  return accounts.filter((a) => a.tipo === "compartilhada" || a.dono === user.id);
}

function ownAccountDefault(accounts, user) {
  return String((accounts.find((a) => a.dono === user.id) || accounts[0] || {}).id ?? "");
}

function txFields(accounts, categories, user) {
  return [
    { name: "date", type: "date", label: "Data", required: true },
    { name: "kind", type: "select", label: "Tipo", required: true, options: kindOptions, value: "gasto", placeholder: false,
      help: "Para pagar uma dívida já cadastrada, use Dívidas › Registrar pagamento, senão ela continua aparecendo como em aberto." },
    { name: "amount_cents", type: "money", label: "Valor", required: true },
    { name: "description", label: "Descrição", max: 160 },
    { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts), value: ownAccountDefault(accounts, user), placeholder: false },
    { name: "category_id", type: "select", label: "Categoria", options: categories, placeholder: "Sem categoria" },
    { name: "competence_date", type: "date", label: "Competência", help: "Mês a que pertence, se for diferente. Exemplo: conta de outubro paga em novembro." },
    { name: "pending", type: "check", label: "Ainda não pago ou recebido (previsto)" },
    { name: "hidden", type: "check", label: "Ocultar da outra pessoa" },
  ];
}

const toBody = ({ pending, ...v }) => ({
  ...v, settled: !pending, account_id: Number(v.account_id), category_id: v.category_id ? Number(v.category_id) : null,
  competence_date: v.competence_date || null,
});

function Row({ item, accounts, categories, user, onChange }) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <tr>
        <td colSpan={6}>
          <Form
            resetOnSuccess={false} fields={txFields(accounts, categories, user).filter((f) => f.name !== "hidden" || item.pessoa_id === user.id)}
            initial={{ date: item.data, kind: item.tipo, amount_cents: item.valor, description: item.descricao, account_id: String(item.conta_id), category_id: item.categoria_id ? String(item.categoria_id) : "", hidden: item.oculto, pending: !item.quitado, competence_date: item.competencia }}
            onSubmit={async (v) => { await api(`/lancamentos/${item.id}`, { method: "PATCH", body: toBody(v) }); setEditing(false); onChange(); }}
            secondary={<button type="button" onClick={() => setEditing(false)}>Cancelar</button>}
          />
        </td>
      </tr>
    );
  }
  const remove = async () => {
    if (!window.confirm("Excluir este lançamento?")) return;
    await api(`/lancamentos/${item.id}`, { method: "DELETE" });
    onChange();
  };
  return (
    <tr>
      <td>{dateBR(item.data)}</td>
      <td>{item.descricao || KINDS[item.tipo]}{item.oculto ? " 🔒" : ""}{item.recorrente ? " ↻" : ""}<div className="muted">{KINDS[item.tipo]} · {item.conta}{item.quitado ? "" : " · previsto"}{item.competencia ? ` · competência ${dateBR(item.competencia)}` : ""}</div></td>
      <td>{item.pessoa}</td>
      <td className={`num ${item.tipo === "renda" ? "pos" : ""}`}>{item.tipo === "renda" ? "" : "−"}{money(item.valor)}</td>
      <td><div className="row" style={{ flexWrap: "nowrap" }}>
        {!item.quitado && <button className="small" type="button" onClick={async () => { await api(`/lancamentos/${item.id}/quitar`, { method: "POST", body: { date: today() } }); onChange(); }}>Quitar</button>}
        <button className="small" type="button" onClick={() => setEditing(true)}>Editar</button>
        <button className="small" type="button" onClick={remove}>Excluir</button>
      </div></td>
    </tr>
  );
}

const toKey = (m) => Number(m.slice(0, 7).replace("-", ""));
const newPayday = () => ({ key: Math.random(), date: today(), amount: "" });

/** Proxima data em que o dia da regra cai, a partir de hoje. */
function nextDay(day) {
  const now = new Date();
  const build = (year, month) => {
    const last = new Date(year, month + 1, 0).getDate();
    return new Date(year, month, Math.min(day, last));
  };
  const date = build(now.getFullYear(), now.getMonth());
  const chosen = date.getDate() >= now.getDate() ? date : build(now.getFullYear(), now.getMonth() + 1);
  return `${chosen.getFullYear()}-${String(chosen.getMonth() + 1).padStart(2, "0")}-${String(chosen.getDate()).padStart(2, "0")}`;
}

function NewIncome({ accounts, categories, user, onChange }) {
  const [paydays, setPaydays] = useState([newPayday()]);
  const [saved, setSaved] = useState("");
  const edit = (key, change) => setPaydays(paydays.map((p) => (p.key === key ? { ...p, ...change } : p)));
  return (
    <section className="card">
      <h2>Salário e outras rendas</h2>
      <p className="muted">Salário: escolha "Todo mês" e adicione uma data para cada recebimento. Cada data repete no mesmo dia dos próximos meses. Freela ou extra: escolha "Só desta vez".</p>
      {saved && <Status level="feito">{saved}</Status>}
      <Form
        submit="Salvar renda" key={accounts.length}
        fields={[
          { name: "description", label: "Nome da renda", required: true, max: 160, placeholder: "Salário, freela…" },
          { name: "frequency", type: "select", label: "Com que frequência", required: true, placeholder: false, value: "mensal",
            options: [{ value: "mensal", label: "Todo mês" }, { value: "unica", label: "Só desta vez" }] },
          { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts), value: ownAccountDefault(accounts, user), placeholder: false },
          { name: "category_id", type: "select", label: "Tag", options: categories, placeholder: "Sem tag" },
          { name: "hidden", type: "check", label: "Ocultar da outra pessoa" },
        ]}
        onSubmit={async ({ frequency, ...v }) => {
          const payments = paydays.map((p, i) => {
            const cents = parseMoney(p.amount);
            if (!p.date) throw new Error(`Informe a data do recebimento ${i + 1}.`);
            if (!cents || Number.isNaN(cents)) throw new Error(`Informe o valor do recebimento ${i + 1}. Exemplo: 1.234,56`);
            return { date: p.date, amount_cents: cents };
          });
          await api("/lancamentos/rendas", { method: "POST", body: {
            ...v, monthly: frequency === "mensal", account_id: Number(v.account_id), category_id: v.category_id ? Number(v.category_id) : null, payments,
          } });
          setPaydays([newPayday()]);
          setSaved(`${v.description}: ${payments.length} recebimento(s) salvo(s).`);
          onChange();
        }}
      >
        <h3>Recebimentos</h3>
        <div className="stack">
          {paydays.map((p, i) => (
            <div key={p.key} className="form-grid paydays">
              <label className="field"><span>Data do recebimento {i + 1}</span>
                <input type="date" value={p.date} onChange={(e) => edit(p.key, { date: e.target.value })} />
              </label>
              <label className="field"><span>Valor do recebimento {i + 1}</span>
                <input inputMode="decimal" placeholder="0,00" value={p.amount} onChange={(e) => edit(p.key, { amount: e.target.value })} />
              </label>
              {paydays.length > 1 && <button type="button" className="small" onClick={() => setPaydays(paydays.filter((o) => o.key !== p.key))}>Remover</button>}
            </div>
          ))}
        </div>
        <div style={{ marginTop: 8 }}>
          <button type="button" className="small" onClick={() => setPaydays([...paydays, newPayday()])}>+ Outra data</button>
        </div>
      </Form>
    </section>
  );
}

function Recurring({ rules, accounts, categories, user, onChange }) {
  return (
    <section className="card">
      <h2>Recorrentes</h2>
      <p className="muted">Tudo o que repete todo mês. Se um mês for diferente, edite só aquele lançamento. Para valer daí em diante, use Alterar.</p>
      <Loading state={rules}>{(list) => (list.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Descrição</th><th>Dia</th><th className="num">Valor</th><th /></tr></thead>
          <tbody>{list.map((r) => (
            <tr key={r.id}>
              <td>{r.descricao || KINDS[r.tipo]}<div className="muted">{KINDS[r.tipo]}{r.ativa ? "" : " · encerrada"}</div></td>
              <td>{r.dia}</td><td className="num">{money(r.valor)}</td>
              <td><Foldout label="Alterar">{(close) => (
                <Form
                  fields={[
                    { name: "from_date", type: "date", label: "Próxima data", required: true, value: nextDay(r.dia), help: "Vale desse mês em diante, sempre nesse dia." },
                    { name: "amount_cents", type: "money", label: "Novo valor", value: r.valor },
                    { name: "active", type: "check", label: "Ativa", value: r.ativa },
                  ]}
                  onSubmit={async (v) => {
                    await api(`/lancamentos/recorrencias/${r.id}`, { method: "PATCH", body: {
                      from_month: toKey(v.from_date), active: v.active, day_of_month: Number(v.from_date.slice(8, 10)),
                      ...(v.amount_cents ? { amount_cents: v.amount_cents } : {}),
                    } });
                    close(); rules.reload(); onChange();
                  }}
                />
              )}</Foldout></td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <Empty>Nenhuma regra criada.</Empty>)}</Loading>
      <Foldout label="Nova regra">{(close) => (
        <Form
          fields={[
            { name: "description", label: "Descrição", max: 160 },
            { name: "kind", type: "select", label: "Tipo", required: true, options: kindOptions, value: "renda", placeholder: false },
            { name: "amount_cents", type: "money", label: "Valor", required: true },
            { name: "first_date", type: "date", label: "Primeira data", required: true, help: "Repete nesse dia. Em meses mais curtos, usa o último dia." },
            { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts), value: ownAccountDefault(accounts, user), placeholder: false },
            { name: "category_id", type: "select", label: "Categoria", options: categories, placeholder: "Sem categoria" },
            { name: "hidden", type: "check", label: "Ocultar da outra pessoa" },
          ]}
          onSubmit={async ({ first_date, ...v }) => {
            await api("/lancamentos/recorrencias", { method: "POST", body: {
              ...v, account_id: Number(v.account_id), category_id: v.category_id ? Number(v.category_id) : null,
              day_of_month: Number(first_date.slice(8, 10)), start_month: toKey(first_date),
            } });
            close(); rules.reload(); onChange();
          }}
        />
      )}</Foldout>
    </section>
  );
}

export default function Lancamentos() {
  const { scope, user } = useApp();
  const accounts = useWritableAccounts();
  const [params, setParams] = useSearchParams();
  const categoriesState = useApi("/contas/categorias");
  const categories = flatten(categoriesState.data || []);
  const filters = {
    inicio: params.get("inicio") || "", fim: params.get("fim") || "", tipo: params.get("tipo") || "",
    categoria_id: params.get("categoria_id") || "", busca: params.get("busca") || "",
    escopo: params.get("escopo") || scope, pagina: params.get("pagina") || "1",
  };
  const list = useApi(`/lancamentos${query(filters)}`);
  const rules = useApi("/lancamentos/recorrencias");
  const setFilter = (name, value) => {
    const next = { ...filters, [name]: value, pagina: "1" };
    setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v && !(v === "1"))), { replace: true });
  };

  return (
    <>
      <h1>Lançamentos</h1>
      <section className="card">
        <h2>Novo lançamento</h2>
        <Form
          key={accounts.length} submit="Adicionar"
          fields={txFields(accounts, categories, user)}
          onSubmit={async (v) => { await api("/lancamentos", { method: "POST", body: toBody(v) }); list.reload(); }}
        />
      </section>

      <NewIncome accounts={accounts} categories={categories} user={user} onChange={() => { list.reload(); rules.reload(); }} />

      <section className="card">
        <h2>Consulta</h2>
        <div className="form-grid">
          <label className="field"><span>De</span><input type="date" value={filters.inicio} onChange={(e) => setFilter("inicio", e.target.value)} /></label>
          <label className="field"><span>Até</span><input type="date" value={filters.fim} onChange={(e) => setFilter("fim", e.target.value)} /></label>
          <label className="field"><span>Tipo</span>
            <select value={filters.tipo} onChange={(e) => setFilter("tipo", e.target.value)}>
              <option value="">Todos</option>{kindOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="field"><span>Categoria</span>
            <select value={filters.categoria_id} onChange={(e) => setFilter("categoria_id", e.target.value)}>
              <option value="">Todas</option>{categories.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <label className="field"><span>Buscar</span><input maxLength={80} value={filters.busca} onChange={(e) => setFilter("busca", e.target.value)} /></label>
        </div>
        <div style={{ marginTop: 12 }}>
          <Loading state={list}>{(data) => (data.itens.length ? (
            <>
              <p className="muted">
                {data.total} lançamento(s)
                {data.entradas > 0 && <> · entradas <span className="pos">{money(data.entradas)}</span></>}
                {data.saidas > 0 && <> · saídas −{money(data.saidas)}</>}
                {data.entradas > 0 && data.saidas > 0 && <> · resultado <ResultValue value={data.resultado} /></>}
                . Inclui os previstos.
              </p>
              <div className="table-wrap"><table>
                <thead><tr><th>Data</th><th>Descrição</th><th>Pessoa</th><th className="num">Valor</th><th /></tr></thead>
                <tbody>{data.itens.map((item) => (
                  <Row key={item.id} item={item} accounts={accounts} categories={categories} user={user} onChange={list.reload} />
                ))}</tbody>
              </table></div>
              <div className="row" style={{ marginTop: 10 }}>
                <button type="button" className="small" disabled={data.pagina <= 1} onClick={() => setParams({ ...Object.fromEntries(params), pagina: data.pagina - 1 })}>Anterior</button>
                <span className="muted">Página {data.pagina} de {Math.max(Math.ceil(data.total / 50), 1)}</span>
                <button type="button" className="small" disabled={data.pagina * 50 >= data.total} onClick={() => setParams({ ...Object.fromEntries(params), pagina: data.pagina + 1 })}>Próxima</button>
              </div>
            </>
          ) : <Empty>Nada encontrado com esses filtros.</Empty>)}</Loading>
        </div>
      </section>

      <Recurring rules={rules} accounts={accounts} categories={categories} user={user} onChange={list.reload} />
    </>
  );
}
