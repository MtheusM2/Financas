import { useState } from "react";
import { Link } from "react-router-dom";
import { api, useApi } from "../api";
import { dateBR, KINDS, money } from "../format";
import { Empty, Form, Loading, Status } from "../ui";
import { Importer as PayslipImporter } from "./Holerites";
import { accountOptions, flatten, useWritableAccounts } from "./Lancamentos";

const MAX_BYTES = 2_000_000;
const LABEL = { nova: "Nova", conciliada: "✓ Já lançada", duplicada: "Já importada" };

async function toBase64(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let text = "";
  for (let i = 0; i < bytes.length; i += 0x8000) text += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(text);
}

function Importer({ accounts, onDone }) {
  const [accountId, setAccountId] = useState("");
  const [preview, setPreview] = useState(null);
  const [lines, setLines] = useState([]);
  const [message, setMessage] = useState(null);
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);
  const categories = flatten(useApi("/contas/categorias").data || []);
  const selected = accountId || String(accounts[0]?.id ?? "");

  const read = async (event) => {
    const file = event.target.files[0];
    event.target.value = "";
    setFailure(null); setMessage(null); setPreview(null);
    if (!file) return;
    if (/\.pdf$/i.test(file.name) || file.type === "application/pdf") {
      setFailure("Este arquivo é um PDF. Holerite se importa no quadro Importar holerite, logo acima; o extrato do banco precisa ser OFX ou CSV.");
      return;
    }
    if (file.size > MAX_BYTES) { setFailure("Arquivo maior que 2 MB."); return; }
    setBusy(true);
    try {
      const data = await api("/conciliacao/previa", { method: "POST", body: { account_id: Number(selected), content_base64: await toBase64(file) } });
      setPreview(data);
      setLines(data.linhas.map((l) => ({ ...l, usar: l.situacao !== "duplicada", lembrar: false })));
    } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  };

  const update = (index, changes) => setLines(lines.map((l, i) => (i === index ? { ...l, ...changes } : l)));

  const confirm = async () => {
    setBusy(true); setFailure(null);
    try {
      const result = await api("/conciliacao/confirmar", { method: "POST", body: {
        account_id: Number(selected),
        lines: lines.filter((l) => l.usar).map((l) => ({
          date: l.data, amount_cents: l.valor, description: l.descricao, fitid: l.fitid, kind: l.tipo,
          category_id: l.categoria_id ? Number(l.categoria_id) : null, match_id: l.conciliar_com?.id ?? null, remember: l.lembrar,
        })),
      } });
      setMessage(`${result.criados} lançamento(s) criado(s), ${result.conciliados} conciliado(s) e ${result.ignorados} ignorado(s).`);
      setPreview(null);
      onDone();
    } catch (error) { setFailure(error.message); } finally { setBusy(false); }
  };

  return (
    <section className="card">
      <h2>Importar extrato</h2>
      <p className="muted">No app ou site do banco, exporte o extrato em OFX ou CSV e envie aqui. Nada é gravado antes da sua confirmação, e importar o mesmo arquivo de novo não duplica.</p>
      <div className="form-grid">
        <label className="field"><span>Conta</span>
          <select value={selected} onChange={(e) => setAccountId(e.target.value)}>
            {accountOptions(accounts).map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        <label className="field"><span>Arquivo do extrato</span><input type="file" accept=".ofx,.csv,.txt" disabled={busy} onChange={read} /></label>
      </div>
      {message && <div style={{ marginTop: 10 }}><Status level="cabe">{message}</Status></div>}
      {failure && <div className="error-box" role="alert">{failure}</div>}
      {preview && (
        <div style={{ marginTop: 12 }}>
          {preview.saldo_banco && <p className="muted">Saldo informado pelo banco em {dateBR(preview.saldo_banco.data)}: <b>{money(preview.saldo_banco.real)}</b>. Depois de importar, confira abaixo.</p>}
          <div className="table-wrap"><table>
            <thead><tr><th>Usar</th><th>Data</th><th>Descrição</th><th className="num">Valor</th><th>Situação</th><th>Tipo</th><th>Categoria</th><th>Lembrar</th></tr></thead>
            <tbody>{lines.map((l, i) => {
              const options = Object.entries(KINDS).filter(([k]) => (k === "renda") === (l.valor > 0));
              const locked = l.situacao !== "nova";
              return (
                <tr key={i}>
                  <td><input type="checkbox" aria-label={`Usar ${l.descricao}`} disabled={l.situacao === "duplicada"} checked={l.usar} onChange={(e) => update(i, { usar: e.target.checked })} /></td>
                  <td>{dateBR(l.data)}</td>
                  <td>{l.descricao}{l.conciliar_com && <div className="muted">Com: {l.conciliar_com.descricao || "lançamento"} de {dateBR(l.conciliar_com.data)}</div>}</td>
                  <td className="num">{money(l.valor)}</td>
                  <td>{LABEL[l.situacao]}</td>
                  <td>{locked ? KINDS[l.tipo] : (
                    <select aria-label="Tipo" value={l.tipo} onChange={(e) => update(i, { tipo: e.target.value })}>{options.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                  )}</td>
                  <td>{locked ? "" : (
                    <select aria-label="Categoria" value={l.categoria_id ?? ""} onChange={(e) => update(i, { categoria_id: e.target.value })}>
                      <option value="">Sem categoria</option>{categories.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                    </select>
                  )}</td>
                  <td>{locked ? "" : <input type="checkbox" aria-label="Lembrar para os próximos" checked={l.lembrar} onChange={(e) => update(i, { lembrar: e.target.checked })} />}</td>
                </tr>
              );
            })}</tbody>
          </table></div>
          <p className="muted">"Lembrar" aplica o mesmo tipo e categoria nos próximos extratos com esse texto.</p>
          <button type="button" className="primary" disabled={busy || !lines.some((l) => l.usar)} onClick={confirm}>Confirmar importação</button>
        </div>
      )}
    </section>
  );
}

function BalanceCheck({ accounts }) {
  const state = useApi("/conciliacao/historico");
  const name = (id) => accounts.find((a) => a.id === id)?.nome || "Conta";
  return (
    <section className="card">
      <h2>Conferir saldo</h2>
      <p className="muted">Informe o saldo que aparece no banco. O sistema compara com o que está registrado até a data.</p>
      <Form
        submit="Conferir"
        fields={[
          { name: "account_id", type: "select", label: "Conta", required: true, options: accountOptions(accounts) },
          { name: "date", type: "date", label: "Data", required: true },
          { name: "real_cents", type: "money", label: "Saldo no banco", required: true },
        ]}
        onSubmit={async (v) => { await api("/conciliacao/saldo", { method: "POST", body: { ...v, account_id: Number(v.account_id) } }); state.reload(); }}
      />
      <div style={{ marginTop: 12 }}>
        <Loading state={state}>{(rows) => (rows.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Data</th><th>Conta</th><th className="num">Banco</th><th className="num">Sistema</th><th className="num">Diferença</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id}><td>{dateBR(r.data)}</td><td>{name(r.conta_id)}</td><td className="num">{money(r.real)}</td><td className="num">{money(r.sistema)}</td><td className="num">{money(r.diferenca)}</td><td>{r.confere ? "✓ Confere" : "! Não confere"}</td></tr>
            ))}</tbody>
          </table></div>
        ) : <Empty>Nenhuma conferência feita.</Empty>)}</Loading>
      </div>
    </section>
  );
}

export default function Conciliacao() {
  const accounts = useWritableAccounts();
  const [, setTick] = useState(0);
  return (
    <>
      <h1>Importar e conciliar</h1>
      {/* Holerite em PDF primeiro: e o que mais se importa no dia a dia. */}
      <PayslipImporter onDone={() => setTick((t) => t + 1)}
        footer={<p className="muted" style={{ marginTop: 10 }}>Histórico, análise e FGTS ficam na tela <Link to="/holerites">Holerites</Link>.</p>} />
      <Importer accounts={accounts} onDone={() => setTick((t) => t + 1)} />
      <BalanceCheck accounts={accounts} />
    </>
  );
}
