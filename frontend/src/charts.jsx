import { useEffect, useRef, useState } from "react";
import { money, moneyShort } from "./format";

function useWidth() {
  const ref = useRef(null);
  const [width, setWidth] = useState(600);
  useEffect(() => {
    if (!ref.current) return undefined;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width || 600));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}

function niceScale(min, max) {
  if (min === max) { min = Math.min(0, min); max = max === 0 ? 100 : Math.max(0, max); }
  const span = max - min;
  const rough = span / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
  const low = Math.floor(min / step) * step;
  const high = Math.ceil(max / step) * step;
  const ticks = [];
  // Somar 0 troca -0 por 0, que apareceria como "R$ -0" no eixo.
  for (let t = low; t <= high + step / 2; t += step) ticks.push(t + 0);
  return { low, high, ticks };
}

export function Legend({ series }) {
  if (series.length < 2) return null;
  return (
    <div className="legend">
      {series.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}
    </div>
  );
}

function Frame({ width, height, scale, labels, children, left = 54, onMove, onLeave, onClick }) {
  const right = 8, top = 8, bottom = 22;
  const innerW = Math.max(width - left - right, 10), innerH = height - top - bottom;
  const y = (value) => top + innerH - ((value - scale.low) / (scale.high - scale.low || 1)) * innerH;
  const every = Math.max(1, Math.ceil(labels.length / Math.max(innerW / 48, 2)));
  const slot = innerW / labels.length;
  const locate = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const index = Math.floor((event.clientX - box.left - left) / slot);
    return index >= 0 && index < labels.length ? index : null;
  };
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`} height={height} role="img"
      onPointerMove={(e) => onMove?.(locate(e))} onPointerLeave={() => onLeave?.()}
      onPointerDown={(e) => onMove?.(locate(e))} onClick={(e) => { const i = locate(e); if (i !== null) onClick?.(i); }}
    >
      {scale.ticks.map((t) => (
        <g key={t}>
          <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--axis)" : "var(--grid)"} />
          <text x={left - 6} y={y(t) + 4} textAnchor="end">{moneyShort(t)}</text>
        </g>
      ))}
      {labels.map((label, i) => (i % every === 0 ? (
        <text key={i} x={left + slot * (i + 0.5)} y={height - 6} textAnchor="middle">{label}</text>
      ) : null))}
      {children({ y, slot, left, innerH, top })}
    </svg>
  );
}

function Tip({ index, count, title, rows }) {
  if (index === null || index === undefined) return null;
  const onRight = index < count / 2;
  return (
    <div className="tooltip" style={{ top: 4, ...(onRight ? { right: 8 } : { left: 60 }) }}>
      <b>{title}</b>
      {rows.map((r) => (
        <div key={r.key}><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, marginRight: 5, background: r.color }} />{r.label}: {money(r.value)}</div>
      ))}
    </div>
  );
}

function DataTable({ labels, series, data }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Período</th>{series.map((s) => <th key={s.key} className="num">{s.label}</th>)}</tr></thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i}><td>{labels[i]}</td>{series.map((s) => <td key={s.key} className="num">{money(row[s.key])}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartBox({ series, labels, data, children }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <div>
      <div className="row between">
        <Legend series={series} />
        <button className="small" type="button" onClick={() => setAsTable(!asTable)}>{asTable ? "Ver gráfico" : "Ver tabela"}</button>
      </div>
      {asTable ? <DataTable labels={labels} series={series} data={data} /> : children}
    </div>
  );
}

/** Linhas sobre um unico eixo. */
export function LineChart({ data, labels, series, height = 220, title = (i) => labels[i] }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const values = data.flatMap((row) => series.map((s) => row[s.key])).filter((v) => v !== null && v !== undefined);
  const scale = niceScale(Math.min(0, ...values), Math.max(0, ...values));
  return (
    <ChartBox series={series} labels={labels} data={data}>
      <div className="chart" ref={ref}>
        <Tip index={hover} count={labels.length} title={hover !== null ? title(hover) : ""}
          rows={hover !== null ? series.map((s) => ({ ...s, value: data[hover][s.key] })).filter((r) => r.value !== null && r.value !== undefined) : []} />
        <Frame width={width} height={height} scale={scale} labels={labels} onMove={setHover} onLeave={() => setHover(null)}>
          {({ y, slot, left, innerH, top }) => (
            <>
              {series.map((s) => {
                const points = data.map((row, i) => (row[s.key] === null || row[s.key] === undefined ? null : `${left + slot * (i + 0.5)},${y(row[s.key])}`)).filter(Boolean);
                return <polyline key={s.key} points={points.join(" ")} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" strokeDasharray={s.dash} />;
              })}
              {hover !== null && (
                <>
                  <line x1={left + slot * (hover + 0.5)} x2={left + slot * (hover + 0.5)} y1={top} y2={top + innerH} stroke="var(--axis)" />
                  {series.map((s) => (data[hover][s.key] === null || data[hover][s.key] === undefined ? null : (
                    <circle key={s.key} cx={left + slot * (hover + 0.5)} cy={y(data[hover][s.key])} r="4.5" fill={s.color} stroke="var(--surface)" strokeWidth="2" />
                  )))}
                </>
              )}
            </>
          )}
        </Frame>
      </div>
    </ChartBox>
  );
}

/** Colunas empilhadas. Series com down:true crescem para baixo a partir do zero. */
export function BarChart({ data, labels, series, height = 220, title = (i) => labels[i], onSelect }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const sum = (row, down) => series.filter((s) => !!s.down === down).reduce((t, s) => t + (row[s.key] || 0), 0);
  const scale = niceScale(Math.min(0, ...data.map((r) => -sum(r, true))), Math.max(0, ...data.map((r) => sum(r, false))));
  if (!data.some((r) => sum(r, true) || sum(r, false))) return <p className="muted">Nada lançado neste período.</p>;
  return (
    <ChartBox series={series} labels={labels} data={data}>
      <div className="chart" ref={ref}>
        <Tip index={hover} count={labels.length} title={hover !== null ? title(hover) : ""}
          rows={hover !== null ? series.map((s) => ({ ...s, value: data[hover][s.key] })).filter((r) => r.value) : []} />
        <Frame width={width} height={height} scale={scale} labels={labels} onMove={setHover} onLeave={() => setHover(null)} onClick={onSelect}>
          {({ y, slot, left }) => data.map((row, i) => {
            const barW = Math.max(Math.min(slot - 3, 28), 2);
            const x = left + slot * (i + 0.5) - barW / 2;
            let up = 0, down = 0;
            return (
              <g key={i} opacity={hover === null || hover === i ? 1 : 0.55}>
                {series.map((s) => {
                  const value = row[s.key] || 0;
                  if (!value) return null;
                  const from = s.down ? -down : up;
                  const to = s.down ? -(down + value) : up + value;
                  if (s.down) down += value; else up += value;
                  const top = Math.min(y(from), y(to));
                  const h = Math.abs(y(from) - y(to));
                  return <rect key={s.key} x={x} y={top + 1} width={barW} height={Math.max(h - 2, 1)} rx={Math.min(3, barW / 2)} fill={s.color} />;
                })}
              </g>
            );
          })}
        </Frame>
      </div>
    </ChartBox>
  );
}

/** Barras horizontais: comparar grandezas de varios grupos. */
export function HBars({ items, onSelect }) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <div className="stack">
      {items.map((item) => (
        <div key={item.key} role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined}
          style={onSelect ? { cursor: "pointer" } : undefined} onClick={() => onSelect?.(item)}
          onKeyDown={(e) => { if (e.key === "Enter") onSelect?.(item); }}>
          <div className="row between" style={{ fontSize: ".875rem" }}>
            <span>{item.label}</span>
            <span>{money(item.value)}{item.share !== undefined ? ` · ${item.share}%` : ""}</span>
          </div>
          <div className="bar"><div style={{ width: `${(item.value / max) * 100}%`, background: item.color || "var(--s1)" }} /></div>
        </div>
      ))}
    </div>
  );
}
