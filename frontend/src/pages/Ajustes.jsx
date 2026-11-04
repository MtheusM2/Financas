import { useState } from "react";
import { api, useApi } from "../api";
import { money } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Form, Loading, Status } from "../ui";

const BLOCKS = {
  resumo: "Resumo do mês", alertas: "Avisos e vencimentos", fluxo: "Fluxo diário", distribuicao: "Para onde foi o dinheiro",
  evolucao: "Evolução em 12 meses", pessoas: "Quem ganhou e quem gastou", recebimentos: "Recebimentos do mês",
  previsao: "Previsão de saldo", tetos: "Tetos por categoria",
};

function Display() {
  const { user, setUser } = useApp();
  const prefs = user.preferencias;
  // A tela muda na hora; se o servidor recusar, volta ao que era.
  const save = async (changes) => {
    setUser({ ...user, preferencias: { ...prefs, ...changes } });
    try {
      setUser(await api("/autenticacao/preferencias", { method: "PATCH", body: changes }));
    } catch {
      setUser(user);
    }
  };
  const move = (index, delta) => {
    const next = [...prefs.blocos];
    const [item] = next.splice(index, 1);
    next.splice(index + delta, 0, item);
    save({ blocos: next });
  };
  const toggle = (block) => save({ ocultos: prefs.ocultos.includes(block) ? prefs.ocultos.filter((b) => b !== block) : [...prefs.ocultos, block] });
  return (
    <section className="card">
      <h2>O que aparece no meu painel</h2>
      <p className="muted">Vale só para você.</p>
      {prefs.blocos.map((block, index) => (
        <div key={block} className="row between" style={{ padding: "6px 0", borderBottom: "1px solid var(--grid)" }}>
          <label className="field check"><input type="checkbox" checked={!prefs.ocultos.includes(block)} onChange={() => toggle(block)} /><span>{BLOCKS[block]}</span></label>
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <button type="button" className="small" aria-label={`Subir ${BLOCKS[block]}`} disabled={index === 0} onClick={() => move(index, -1)}>↑</button>
            <button type="button" className="small" aria-label={`Descer ${BLOCKS[block]}`} disabled={index === prefs.blocos.length - 1} onClick={() => move(index, 1)}>↓</button>
          </div>
        </div>
      ))}
      <label className="field check" style={{ marginTop: 12 }}>
        <input type="checkbox" checked={prefs.alertas_email !== false} onChange={(e) => save({ alertas_email: e.target.checked })} />
        <span>Receber por e-mail o resumo diário de contas a vencer e outros alertas</span>
      </label>
    </section>
  );
}

function Accounts() {
  const { user, reloadAccounts } = useApp();
  const state = useApi("/contas");
  const refresh = () => { state.reload(); reloadAccounts(); };
  return (
    <section className="card">
      <h2>Contas</h2>
      <Loading state={state}>{(list) => list.map((a) => {
        const mine = a.tipo === "compartilhada" || a.dono === user.id;
        return (
          <div key={a.id} className="row between" style={{ padding: "8px 0", borderBottom: "1px solid var(--grid)" }}>
            <div>{a.nome}{a.oculta ? " 🔒" : ""}{a.arquivada ? " (arquivada)" : ""}<div className="muted">{a.tipo === "compartilhada" ? "Compartilhada" : "Pessoal"} · Saldo inicial {money(a.saldo_inicial)}</div></div>
            {mine && (
              <Foldout label="Editar">{(close) => (
                <Form
                  resetOnSuccess={false}
                  fields={[
                    { name: "name", label: "Nome", required: true, max: 80, value: a.nome },
                    { name: "opening_balance_cents", type: "money", label: "Saldo inicial", value: a.saldo_inicial },
                    a.tipo === "pessoal" && { name: "hidden", type: "check", label: "Ocultar esta conta da outra pessoa", value: a.oculta },
                    { name: "archived", type: "check", label: "Arquivar", value: a.arquivada },
                  ]}
                  onSubmit={async (v) => { await api(`/contas/${a.id}`, { method: "PATCH", body: { ...v, opening_balance_cents: v.opening_balance_cents ?? 0 } }); close(); refresh(); }}
                />
              )}</Foldout>
            )}
          </div>
        );
      })}</Loading>
      <div style={{ marginTop: 10 }}>
        <Foldout label="Nova conta">{(close) => (
          <Form
            fields={[
              { name: "name", label: "Nome", required: true, max: 80 },
              { name: "kind", type: "select", label: "Tipo", placeholder: false, value: "pessoal", options: [{ value: "pessoal", label: "Pessoal" }, { value: "compartilhada", label: "Compartilhada" }] },
              { name: "opening_balance_cents", type: "money", label: "Saldo inicial" },
            ]}
            onSubmit={async (v) => { await api("/contas", { method: "POST", body: { ...v, opening_balance_cents: v.opening_balance_cents ?? 0 } }); close(); refresh(); }}
          />
        )}</Foldout>
      </div>
    </section>
  );
}

function CategoryNode({ node, depth, onChange }) {
  return (
    <>
      <div className="row between" style={{ padding: "4px 0", paddingLeft: depth * 16 }}>
        <span>{node.nome}{node.essencial ? <span className="pill" style={{ marginLeft: 6 }}>Essencial</span> : null}</span>
        <button type="button" className="small" onClick={async () => { await api(`/contas/categorias/${node.id}`, { method: "PATCH", body: { essential: !node.essencial } }); onChange(); }}>
          {node.essencial ? "Tirar de essencial" : "Marcar essencial"}
        </button>
      </div>
      {node.filhas.map((c) => <CategoryNode key={c.id} node={c} depth={depth + 1} onChange={onChange} />)}
    </>
  );
}

function Categories() {
  const state = useApi("/contas/categorias");
  const flat = (tree) => tree.map((c) => ({ value: String(c.id), label: c.nome }));
  return (
    <section className="card">
      <h2>Categorias e tags</h2>
      <p className="muted">Use em lançamentos, rendas e dívidas. As essenciais formam a base da reserva de emergência.</p>
      <Loading state={state}>{(tree) => tree.map((n) => <CategoryNode key={n.id} node={n} depth={0} onChange={state.reload} />)}</Loading>
      <div style={{ marginTop: 10 }}>
        <Foldout label="Nova categoria ou tag">{(close) => (
          <Form
            fields={[
              { name: "name", label: "Nome", required: true, max: 60 },
              { name: "parent_id", type: "select", label: "Dentro de", options: flat(state.data || []), placeholder: "Nenhuma" },
              { name: "essential", type: "check", label: "Essencial" },
            ]}
            onSubmit={async (v) => { await api("/contas/categorias", { method: "POST", body: { ...v, parent_id: v.parent_id ? Number(v.parent_id) : null } }); close(); state.reload(); }}
          />
        )}</Foldout>
      </div>
    </section>
  );
}

function TwoFactor() {
  const { user, setUser } = useApp();
  const [setup, setSetup] = useState(null);
  return (
    <section className="card">
      <h2>Confirmação em dois passos</h2>
      {user.dois_fatores ? (
        <>
          <Status level="cabe">Ativa na sua conta.</Status>
          <Form
            submit="Desativar" fields={[{ name: "totp", type: "code", label: "Código do app autenticador" }]}
            onSubmit={async (v) => setUser(await api("/autenticacao/2fa/desativar", { method: "POST", body: v }))}
          />
        </>
      ) : setup ? (
        <>
          <p>No app autenticador, adicione esta chave manualmente:</p>
          <p><code style={{ overflowWrap: "anywhere" }}>{setup.chave}</code></p>
          <Form
            submit="Ativar" fields={[{ name: "totp", type: "code", label: "Código gerado pelo app" }]}
            onSubmit={async (v) => { setUser(await api("/autenticacao/2fa/ativar", { method: "POST", body: v })); setSetup(null); }}
          />
        </>
      ) : (
        <button type="button" onClick={async () => setSetup(await api("/autenticacao/2fa/iniciar", { method: "POST" }))}>Configurar</button>
      )}
    </section>
  );
}

function Audit() {
  const state = useApi("/auditoria?limit=50");
  const { users } = useApp();
  const name = (id) => users.find((u) => u.id === id)?.nome || "Sistema";
  return (
    <section className="card">
      <h2>Histórico de alterações</h2>
      <Loading state={state}>{(rows) => (rows.length ? (
        <div className="table-wrap" style={{ maxHeight: 340, overflowY: "auto" }}><table>
          <thead><tr><th>Quando</th><th>Quem</th><th>O quê</th><th>Rastreio</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}><td>{new Date(r.em).toLocaleString("pt-BR")}</td><td>{name(r.usuario)}</td><td>{r.acao.replace(/_/g, " ")} {r.entidade}</td><td className="muted">{r.rastreio}</td></tr>
          ))}</tbody>
        </table></div>
      ) : <Empty>Nada registrado.</Empty>)}</Loading>
    </section>
  );
}

export default function Ajustes() {
  return (
    <>
      <h1>Ajustes</h1>
      <Display />
      <Accounts />
      <Categories />
      <TwoFactor />
      <Audit />
    </>
  );
}
