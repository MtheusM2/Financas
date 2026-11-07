import { Link, useNavigate } from "react-router-dom";
import { query, useApi } from "../api";
import { BarChart, HBars, LineChart } from "../charts";
import { dateBR, KINDS, money, monthName, OUTFLOW_KINDS } from "../format";
import { useApp } from "../main";
import { Empty, Foldout, Loading, ResultValue, Status, Tile } from "../ui";
import { Ceilings, Forecast } from "./Planejamento";

// Mesmas cores em todos os graficos: entrada verde, saida laranja, fora do escopo roxo, saldo azul.
const COLORS = {
  gasto: "var(--s2)", fora_escopo: "var(--s7)", divida: "var(--s5)", investimento: "var(--s1)",
  guardado: "var(--s3)", lazer: "var(--s4)",
};
const pad = (n) => String(n).padStart(2, "0");
const ALERT_LEVEL = { critico: "compromete", atencao: "atencao", info: "info" };

const alertRow = (a, i) => (
  <Status key={`${a.tipo}-${a.titulo}-${i}`} level={ALERT_LEVEL[a.nivel]}>
    <b>{a.titulo}</b>: {money(a.valor)}{a.detalhe ? `. ${a.detalhe}` : ""}
    {(a.tipo === "divida" || a.tipo === "financiamento") && <> <Link to="/compromissos">Registrar pagamento</Link></>}
  </Status>
);

export default function Painel() {
  const { scope, period, user, modules, accounts } = useApp();
  const navigate = useNavigate();
  const params = query({ ano: period.ano, mes: period.mes, escopo: scope });
  const summary = useApi(`/painel/resumo${params}`);
  const flow = useApi(`/painel/fluxo${params}`);
  const budget = useApi(modules.includes("orcamento") ? `/orcamento/resumo${query({ escopo: scope })}` : null);
  const alerts = useApi(modules.includes("alertas") ? "/alertas" : null);
  const prefs = user.preferencias;
  const showing = (block) => !prefs.ocultos.includes(block);
  const monthRange = { inicio: `${period.ano}-${pad(period.mes)}-01`, fim: `${period.ano}-${pad(period.mes)}-31`, escopo: scope };
  const openList = (params2) => navigate(`/lancamentos${query({ ...monthRange, ...params2 })}`);

  const blocks = {
    resumo: () => (
      <Loading state={summary} key="resumo">{(data) => {
        const t = data.totais;
        const share = (v) => (t.renda ? `${Math.round((v / t.renda) * 100)}% da renda` : undefined);
        const expected = data.recebimentos.filter((r) => r.previsto).reduce((sum, r) => sum + r.valor, 0);
        const now = new Date();
        const ongoing = period.ano * 100 + period.mes >= now.getFullYear() * 100 + now.getMonth() + 1;
        const noOpening = accounts.every((a) => !a.saldo_inicial);
        return (
          <>
            <div className="tiles">
              <Tile label="Renda total" value={money(t.renda)} hint={expected ? `já recebida · falta receber ${money(expected)}` : "já recebida"} />
              <Tile label="Gastos" value={money(t.gasto)} hint={share(t.gasto)} />
              <Tile label="Fora do escopo" value={money(t.fora_escopo)} hint={share(t.fora_escopo)} />
              <Tile label="Dívidas pagas" value={money(t.divida)} hint={share(t.divida)} />
              <Tile label="Investimentos" value={money(t.investimento)} hint={share(t.investimento)} />
              <Tile label="Guardado" value={money(t.guardado)} hint={share(t.guardado)} />
              <Tile label="Lazer" value={money(t.lazer)} hint={share(t.lazer)} />
              <Tile label="Sobra do mês" value={<ResultValue value={t.restante} />} hint={`renda menos todas as saídas${t.renda ? ` · ${share(t.restante)}` : ""}`} />
              <Tile label={ongoing ? "Saldo até agora" : "Saldo no fim do mês"} value={<ResultValue value={data.saldo_final} />}
                hint={noOpening ? "sem saldo inicial das contas" : "inclui meses anteriores e saldo inicial"} />
            </div>
            <p className="muted" style={{ marginTop: -6, marginBottom: 14 }}>
              Os quadros mostram só o que já entrou ou saiu. Contas a pagar e valores previstos aparecem na Previsão de saldo.
              {noOpening && " Para o saldo bater com o banco, informe o saldo inicial de cada conta em Ajustes › Contas."}
            </p>
          </>
        );
      }}</Loading>
    ),
    alertas: () => (
      <div key="alertas">
        {budget.data && budget.data.livre < 0 && (
          <Status level="compromete">
            Os compromissos e planos somam {money(-budget.data.livre)} a mais do que a renda média de {money(budget.data.renda_media)}. Veja em Objetivos o que ajustar.
          </Status>
        )}
        {(alerts.data || []).slice(0, 6).map(alertRow)}
        {(alerts.data || []).length > 6 && (
          <div style={{ marginBottom: 14 }}>
            <Foldout label={`Ver mais ${alerts.data.length - 6} aviso(s)`}>{() => alerts.data.slice(6).map(alertRow)}</Foldout>
          </div>
        )}
      </div>
    ),
    previsao: () => (modules.includes("previsao") ? <div key="previsao"><Forecast /></div> : null),
    tetos: () => (modules.includes("orcamento") ? <div key="tetos"><Ceilings compact /></div> : null),
    fluxo: () => (
      <section className="card" key="fluxo">
        <h2>Fluxo de {monthName(period.mes)}/{period.ano}</h2>
        <Loading state={flow}>{(data) => {
          const rows = data.dias.map((d) => ({ ...d, entradas: d.entradas, saidas_normais: d.saidas - d.fora_escopo }));
          const labels = rows.map((r) => String(r.dia));
          const title = (i) => `Dia ${labels[i]}`;
          return (
            <>
              <BarChart
                data={rows} labels={labels} title={title} height={200}
                series={[
                  { key: "entradas", label: "Entradas", color: "var(--s3)" },
                  { key: "saidas_normais", label: "Saídas", color: "var(--s2)", down: true },
                  { key: "fora_escopo", label: "Fora do escopo", color: "var(--s7)", down: true },
                ]}
                onSelect={(i) => {
                  const day = `${period.ano}-${pad(period.mes)}-${pad(rows[i].dia)}`;
                  if (rows[i].entradas || rows[i].saidas) openList({ inicio: day, fim: day });
                }}
              />
              <h3>Saldo ao longo do mês</h3>
              <LineChart data={rows} labels={labels} title={title} height={160} series={[{ key: "saldo", label: "Saldo", color: "var(--s1)" }]} />
              <p className="muted">Toque em um dia para ver os lançamentos.</p>
            </>
          );
        }}</Loading>
      </section>
    ),
    distribuicao: () => (
      <section className="card" key="distribuicao">
        <h2>Para onde foi o dinheiro</h2>
        <Loading state={summary}>{(data) => {
          const t = data.totais;
          const items = OUTFLOW_KINDS.map((k) => ({
            key: k, label: KINDS[k], value: t[k], color: COLORS[k],
            share: t.saidas ? Math.round((t[k] / t.saidas) * 100) : 0,
          })).filter((i) => i.value > 0);
          return items.length
            ? <HBars items={items} onSelect={(item) => openList({ tipo: item.key })} />
            : <Empty>Nenhuma saída neste mês.</Empty>;
        }}</Loading>
      </section>
    ),
    evolucao: () => (
      <section className="card" key="evolucao">
        <h2>Evolução em 12 meses</h2>
        <Loading state={summary}>{(data) => (
          <LineChart
            data={data.evolucao}
            labels={data.evolucao.map((e) => monthName(e.mes))}
            title={(i) => `${monthName(data.evolucao[i].mes)}/${data.evolucao[i].ano}`}
            series={[
              { key: "renda", label: "Renda", color: "var(--s3)" },
              { key: "saidas", label: "Saídas", color: "var(--s2)" },
              { key: "restante", label: "Sobra", color: "var(--s1)", dash: "5 4" },
            ]}
          />
        )}</Loading>
      </section>
    ),
    pessoas: () => (
      <section className="card" key="pessoas">
        <h2>Quem ganhou e quem gastou</h2>
        <Loading state={summary}>{(data) => (data.pessoas.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Pessoa</th><th className="num">Renda</th><th className="num">Saídas</th><th className="num">Fora do escopo</th><th /></tr></thead>
              <tbody>
                {data.pessoas.map((p) => (
                  <tr key={p.id}>
                    <td>{p.nome}</td><td className="num">{money(p.renda)}</td><td className="num">{money(p.saidas)}</td><td className="num">{money(p.fora_escopo)}</td>
                    <td><button className="small" type="button" onClick={() => openList({ escopo: `pessoa:${p.id}`, tipo: "fora_escopo" })}>Detalhes</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>Sem movimentação neste mês.</Empty>)}</Loading>
      </section>
    ),
    recebimentos: () => (
      <section className="card" key="recebimentos">
        <h2>Recebimentos do mês</h2>
        <Loading state={summary}>{(data) => (data.recebimentos.length ? (
          <div className="table-wrap">
            <table>
              <tbody>
                {data.recebimentos.map((r, i) => (
                  <tr key={i}><td>{dateBR(r.data)}</td><td>{r.pessoa}</td><td>{r.descricao}{r.previsto ? " (previsto)" : ""}</td><td className="num">{money(r.valor)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>Nenhum recebimento lançado neste mês.</Empty>)}</Loading>
      </section>
    ),
  };

  return (
    <>
      <h1>Painel</h1>
      {prefs.blocos.filter((b) => blocks[b] && showing(b)).map((b) => blocks[b]())}
    </>
  );
}
