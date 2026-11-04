import { LineChart } from "../charts";
import { money } from "../format";
import { Status } from "../ui";

/** Mostra se o plano cabe, a conta usada e as alternativas. So apresenta; nao altera nada. */
export default function Avaliacao({ result }) {
  if (!result) return null;
  const { orcamento: b, alternativas: alt } = result;
  const options = [
    { key: "plano", label: "Plano pedido", color: "var(--s1)", serie: result.plano_original },
    alt.aumentar_prazo && { key: "prazo", label: "Prazo maior", color: "var(--s2)", serie: alt.aumentar_prazo.serie },
    alt.reduzir_valor && { key: "valor", label: "Valor menor", color: "var(--s3)", serie: alt.reduzir_valor.serie },
    alt.pausar_investimentos && { key: "pausa", label: "Reduzindo investimentos", color: "var(--s4)", serie: alt.pausar_investimentos.serie, dash: "5 4" },
  ].filter(Boolean);
  const length = Math.max(...options.map((o) => o.serie.length), 1);
  const data = Array.from({ length }, (_, i) => Object.fromEntries(options.map((o) => [o.key, o.serie[i] ?? null])));
  const labels = data.map((_, i) => `${i + 1}`);

  return (
    <div style={{ marginTop: 12 }}>
      <Status level={result.situacao}>
        {result.mensagem} Este plano pede <b>{money(result.aporte_mensal)}</b> por mês.
      </Status>
      <div className="table-wrap"><table><tbody>
        <tr><td>Renda média ({b.meses_considerados} mês/meses)</td><td className="num">{money(b.renda_media)}</td></tr>
        <tr><td>− Dívidas, financiamentos e gastos fixos</td><td className="num">{money(b.obrigacoes.total)}</td></tr>
        <tr><td>= Disponível</td><td className="num">{money(b.disponivel)}</td></tr>
        <tr><td>− Objetivos e desafios já planejados</td><td className="num">{money(b.planos.objetivos + b.planos.desafios)}</td></tr>
        <tr><td>− Investimentos planejados</td><td className="num">{money(b.planos.investimentos)}</td></tr>
        <tr><td><b>= Folga por mês</b></td><td className="num"><b>{money(b.livre)}</b></td></tr>
      </tbody></table></div>
      {result.situacao !== "cabe" && (
        <>
          <h3>Caminhos possíveis</h3>
          <ul style={{ paddingLeft: 18, margin: "0 0 8px" }}>
            {alt.aumentar_prazo && <li>Aumentar o prazo para <b>{alt.aumentar_prazo.meses} meses</b>, guardando {money(alt.aumentar_prazo.aporte_mensal)} por mês.</li>}
            {alt.reduzir_valor && <li>Manter o prazo e chegar a <b>{money(alt.reduzir_valor.valor_possivel)}</b>, guardando {money(alt.reduzir_valor.aporte_mensal)} por mês.</li>}
            {alt.pausar_investimentos && (
              <li>
                Reduzir os investimentos em <b>{money(alt.pausar_investimentos.reduzir_por_mes)}</b> por mês durante {alt.pausar_investimentos.meses} meses.
                Vocês deixariam de aportar {money(alt.pausar_investimentos.deixa_de_aportar)} e de acumular {money(alt.pausar_investimentos.deixa_de_acumular)}, considerando o rendimento informado.
              </li>
            )}
            {!alt.aumentar_prazo && !alt.pausar_investimentos && <li>Hoje não há folga para este plano. Reduzir obrigações ou aumentar a renda vem antes dele.</li>}
          </ul>
          <LineChart data={data} labels={labels} title={(i) => `Mês ${labels[i]}`} series={options} height={200} />
          <p className="muted">Simulação feita com os dados de vocês, sem recomendar produtos. A decisão é de vocês, e nada foi alterado.</p>
        </>
      )}
    </div>
  );
}
