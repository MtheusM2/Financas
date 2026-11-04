import { useState } from "react";
import { api, query, useApi } from "../api";
import { BarChart, LineChart } from "../charts";
import { KINDS, money, monthLabel, monthName } from "../format";
import { useApp } from "../main";
import { Empty, Loading, Progress, ResultValue, Tile } from "../ui";

const ROWS = [["renda", KINDS.renda], ["gasto", KINDS.gasto], ["fora_escopo", KINDS.fora_escopo], ["divida", KINDS.divida],
  ["investimento", KINDS.investimento], ["guardado", KINDS.guardado], ["lazer", KINDS.lazer], ["saidas", "Total de saídas"], ["restante", "Restante"]];
const key = (m) => Number(m.replace("-", ""));

function CompareTable({ data, labelA, labelB }) {
  return (
    <div className="table-wrap"><table>
      <thead><tr><th /><th className="num">{labelA}</th><th className="num">{labelB}</th><th className="num">Diferença</th><th className="num">%</th></tr></thead>
      <tbody>{ROWS.map(([id, label]) => (
        <tr key={id}>
          <td>{label}</td><td className="num">{money(data[id].a)}</td><td className="num">{money(data[id].b)}</td>
          <td className="num">{money(data[id].diferenca)}</td><td className="num">{data[id].percentual === null ? "—" : `${data[id].percentual}%`}</td>
        </tr>
      ))}</tbody>
    </table></div>
  );
}

function Monthly() {
  const { period, scope } = useApp();
  const state = useApi(`/relatorios/mensal${query({ ano: period.ano, mes: period.mes, escopo: scope })}`);
  const [message, setMessage] = useState(null);
  const label = `${monthName(period.mes)}/${period.ano}`;
  return (
    <section className="card">
      <h2>Relatório de {label}</h2>
      <Loading state={state}>{(data) => (
        <>
          <p className="muted">
            {data.fechamento ? (data.fechamento.situacao === "fechado" ? "✓ Mês fechado." : "! Mês reaberto porque foi alterado depois do fechamento.") : "Mês ainda aberto."}
          </p>
          <CompareTable data={data.comparado_mes_anterior} labelA="Mês anterior" labelB="Este mês" />
          <div className="row" style={{ marginTop: 10 }}>
            <button type="button" className="small" onClick={async () => {
              await api(`/relatorios/fechamentos/${period.ano}/${period.mes}`, { method: "POST" });
              setMessage(`Registro de ${label} gravado.`);
              state.reload();
            }}>{data.fechamento ? "Fechar de novo" : "Fechar este mês"}</button>
            {message && <span className="muted" role="status">{message}</span>}
          </div>
        </>
      )}</Loading>
    </section>
  );
}

function Compare() {
  const { scope } = useApp();
  const year = new Date().getFullYear();
  const [mode, setMode] = useState({ aI: `${year - 1}-01`, aF: `${year - 1}-12`, bI: `${year}-01`, bF: `${year}-12` });
  const valid = mode.aI && mode.aF && mode.bI && mode.bF && mode.aI <= mode.aF && mode.bI <= mode.bF;
  const state = useApi(valid ? `/relatorios/comparar${query({ a_inicio: key(mode.aI), a_fim: key(mode.aF), b_inicio: key(mode.bI), b_fim: key(mode.bF), escopo: scope })}` : null);
  const field = (name, label) => (
    <label className="field"><span>{label}</span><input type="month" value={mode[name]} onChange={(e) => setMode({ ...mode, [name]: e.target.value })} /></label>
  );
  return (
    <section className="card">
      <h2>Comparar períodos</h2>
      <p className="muted">Mês contra mês, ano contra ano ou qualquer período.</p>
      <div className="form-grid">{field("aI", "Período A: de")}{field("aF", "Período A: até")}{field("bI", "Período B: de")}{field("bF", "Período B: até")}</div>
      <div style={{ marginTop: 12 }}>
        {valid ? <Loading state={state}>{(data) => <CompareTable data={data} labelA="Período A" labelB="Período B" />}</Loading> : <p className="error-box">O início precisa vir antes do fim.</p>}
      </div>
    </section>
  );
}

function History() {
  const { scope, period } = useApp();
  const [group, setGroup] = useState("mes");
  const span = group === "mes" ? { inicio: (period.ano - 1) * 100 + period.mes, fim: period.ano * 100 + period.mes } : { inicio: (period.ano - 4) * 100 + 1, fim: period.ano * 100 + 12 };
  const state = useApi(`/relatorios/serie${query({ ...span, agrupar: group, escopo: scope })}`);
  const gains = useApi(`/relatorios/ganhos-perdas${query({ ...span, escopo: scope })}`);
  return (
    <section className="card">
      <div className="row between">
        <h2>Ganhos, perdas e evolução</h2>
        <select style={{ width: "auto" }} aria-label="Agrupar por" value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="mes">Mês a mês</option><option value="ano">Ano a ano</option>
        </select>
      </div>
      <Loading state={gains}>{(g) => (
        <div className="tiles">
          <Tile label="Resultado do período" value={<ResultValue value={g.resultado_periodo} />} />
          <Tile label="Aportado em investimentos" value={money(g.investimentos.aportado)} hint="Total até hoje" />
          <Tile label="Valor atual investido" value={money(g.investimentos.valor_atual)} />
          <Tile label="Ganho ou perda investindo" value={<ResultValue value={g.investimentos.resultado} />} />
        </div>
      )}</Loading>
      <Loading state={state}>{(rows) => (
        <>
          <BarChart
            data={rows} labels={rows.map((r) => monthLabel(r.periodo))} height={200}
            series={[{ key: "renda", label: "Renda", color: "var(--s1)" }, { key: "saidas", label: "Saídas", color: "var(--s2)", down: true }]}
          />
          <h3>Investido e guardado no período</h3>
          <LineChart
            data={rows} labels={rows.map((r) => monthLabel(r.periodo))} height={170}
            series={[{ key: "investimento", label: "Investimentos", color: "var(--s1)" }, { key: "guardado", label: "Guardado", color: "var(--s2)" }, { key: "divida", label: "Dívidas pagas", color: "var(--s3)" }]}
          />
        </>
      )}</Loading>
    </section>
  );
}

function Dre() {
  const { period, scope } = useApp();
  const [regime, setRegime] = useState("competencia");
  const [span, setSpan] = useState("mes");
  const range = span === "mes"
    ? { inicio: period.ano * 100 + period.mes, fim: period.ano * 100 + period.mes }
    : { inicio: period.ano * 100 + 1, fim: period.ano * 100 + 12 };
  const state = useApi(`/relatorios/dre${query({ ...range, regime, escopo: scope })}`);
  const line = (label, value, strong) => (
    <tr key={label}><td>{strong ? <b>{label}</b> : label}</td><td className="num">{strong ? <b>{money(value)}</b> : money(value)}</td></tr>
  );
  return (
    <section className="card">
      <div className="row between">
        <h2>DRE: resultado {span === "mes" ? `de ${monthName(period.mes)}/${period.ano}` : `de ${period.ano}`}</h2>
        <div className="row">
          <select style={{ width: "auto" }} aria-label="Período da DRE" value={span} onChange={(e) => setSpan(e.target.value)}>
            <option value="mes">No mês</option><option value="ano">No ano</option>
          </select>
          <select style={{ width: "auto" }} aria-label="Regime" value={regime} onChange={(e) => setRegime(e.target.value)}>
            <option value="competencia">Competência</option><option value="caixa">Caixa</option>
          </select>
        </div>
      </div>
      <p className="muted">
        {regime === "competencia"
          ? "Competência: considera o mês a que cada valor pertence, mesmo que ainda não tenha sido pago."
          : "Caixa: considera só o que realmente entrou ou saiu no período."}
      </p>
      <Loading state={state}>{(d) => (
        <>
          <div className="tiles">
            <Tile label={d.resultado >= 0 ? "Sobra do período" : "Falta no período"} value={<ResultValue value={d.resultado} />} hint={d.margem !== null ? `${d.margem}% da renda` : undefined} />
            <Tile label="Sobra depois de investir e guardar" value={<ResultValue value={d.sobra_apos_guardar} />} />
          </div>
          <div className="table-wrap"><table><tbody>
            {line("Receitas", d.receitas.total, true)}
            {d.receitas.itens.map((i) => line(`  ${i.nome}`, i.valor))}
            {line("Despesas", d.despesas.total, true)}
            {d.despesas.grupos.filter((g) => g.total).flatMap((g) => [line(KINDS[g.tipo], g.total), ...g.itens.map((i) => line(`  ${g.tipo}: ${i.nome}`, i.valor))])}
            {line("Resultado", d.resultado, true)}
            {line("Investimentos (fora do resultado)", d.fora_do_resultado.investimento)}
            {line("Guardado (fora do resultado)", d.fora_do_resultado.guardado)}
          </tbody></table></div>
        </>
      )}</Loading>
    </section>
  );
}

function Tax() {
  const { period } = useApp();
  const [year, setYear] = useState(period.ano - 1);
  const state = useApi(`/relatorios/imposto${query({ ano: year })}`);
  const years = Array.from({ length: 6 }, (_, i) => period.ano - i);
  return (
    <section className="card">
      <div className="row between">
        <h2>Apoio ao Imposto de Renda</h2>
        <select style={{ width: "auto" }} aria-label="Ano-calendário" value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>
      <p className="muted">Reúne os dados registrados no ano para ajudar no preenchimento. Não substitui os informes oficiais nem um contador.</p>
      <Loading state={state}>{(d) => {
        const people = {};
        d.rendimentos.forEach((r) => { people[r.pessoa] = (people[r.pessoa] || 0) + r.valor; });
        return (
          <div className="table-wrap"><table><tbody>
            {Object.entries(people).map(([name, value]) => <tr key={name}><td>Rendimentos de {name}</td><td className="num">{money(value)}</td></tr>)}
            {d.contas.map((a) => <tr key={a.nome}><td>Saldo em 31/12: {a.nome}</td><td className="num">{money(a.saldo)}</td></tr>)}
            {d.investimentos.map((i) => <tr key={i.nome}><td>Aportado até 31/12: {i.nome}</td><td className="num">{money(i.aportado_ate_fim_do_ano)}</td></tr>)}
            {d.dividas.map((x) => <tr key={x.nome}><td>Saldo em 31/12: {x.nome}</td><td className="num">{money(x.saldo_fim_do_ano)}</td></tr>)}
          </tbody></table></div>
        );
      }}</Loading>
      <div className="row" style={{ marginTop: 10 }}>
        <a className="button" href={`/api/relatorios/imposto.csv${query({ ano: year })}`} download>Baixar resumo (CSV)</a>
        <a className="button" href={`/api/relatorios/lancamentos.csv${query({ inicio: `${year}-01-01`, fim: `${year}-12-31` })}`} download>Baixar lançamentos (CSV)</a>
      </div>
    </section>
  );
}

const TYPES = { objetivo: "Objetivo", reserva: "Reserva", desafio: "Desafio", investimento: "Investimento", divida: "Dívida", financiamento: "Financiamento" };

function ProgressOverTime() {
  const state = useApi("/relatorios/progresso");
  const isCount = (t) => t === "divida" || t === "financiamento";
  return (
    <section className="card">
      <h2>Progresso ao longo do tempo</h2>
      <p className="muted">Cada fechamento grava um ponto. Objetivos, metas, investimentos e o caminho até quitar as dívidas.</p>
      <Loading state={state}>{(items) => (items.length ? items.map((item) => {
        const current = item.agora.atual;
        const pct = item.meta ? (current / item.meta) * 100 : null;
        return (
          <div key={`${item.tipo}${item.id}`} className="card">
            <div className="row between"><b>{item.nome}</b><span className="pill">{TYPES[item.tipo]}</span></div>
            <p className="muted">
              {isCount(item.tipo)
                ? `${current}${item.meta ? ` de ${item.meta}` : ""} parcelas pagas${item.agora.saldo !== null && item.agora.saldo !== undefined ? ` · faltam ${money(item.agora.saldo)}` : ""}`
                : `${money(current)}${item.meta ? ` de ${money(item.meta)}` : ""}${item.agora.previsto !== null && item.agora.previsto !== undefined ? ` · ${item.tipo === "investimento" ? "aportado" : "previsto"} ${money(item.agora.previsto)}` : ""}`}
            </p>
            {pct !== null && <Progress value={pct} />}
            {item.pontos.length > 1 && (
              isCount(item.tipo) ? (
                <div className="table-wrap" style={{ marginTop: 8 }}><table><tbody>
                  {item.pontos.map((p) => <tr key={p.periodo}><td>{monthLabel(p.periodo)}</td><td className="num">{p.atual} pagas</td><td className="num">{money(p.saldo)}</td></tr>)}
                </tbody></table></div>
              ) : (
                <div style={{ marginTop: 8 }}>
                  <LineChart
                    data={item.pontos} labels={item.pontos.map((p) => monthLabel(p.periodo))} height={150}
                    series={[{ key: "atual", label: "Realizado", color: "var(--s1)" }, ...(item.pontos.some((p) => p.previsto !== null && p.previsto !== undefined) ? [{ key: "previsto", label: item.tipo === "investimento" ? "Aportado" : "Previsto", color: "var(--s2)" }] : [])]}
                  />
                </div>
              )
            )}
          </div>
        );
      }) : <Empty>Nada para acompanhar ainda.</Empty>)}</Loading>
    </section>
  );
}

function Closings() {
  const state = useApi("/relatorios/fechamentos");
  return (
    <section className="card">
      <h2>Registros mensais</h2>
      <Loading state={state}>{(rows) => (rows.length ? (
        <div className="table-wrap"><table>
          <thead><tr><th>Mês</th><th>Situação</th><th className="num">Renda</th><th className="num">Saídas</th><th className="num">Restante</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={`${r.ano}${r.mes}`}>
              <td>{monthName(r.mes)}/{r.ano}</td><td>{r.situacao === "fechado" ? "✓ Fechado" : "! Reaberto"}</td>
              <td className="num">{money(r.totais.renda)}</td><td className="num">{money(r.totais.saidas)}</td><td className="num">{money(r.totais.restante)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <Empty>Os meses passados são fechados automaticamente e aparecem aqui.</Empty>)}</Loading>
    </section>
  );
}

export default function Relatorios() {
  return (
    <>
      <h1>Relatórios</h1>
      <Monthly />
      <Dre />
      <History />
      <Compare />
      <ProgressOverTime />
      <Closings />
      <Tax />
    </>
  );
}
