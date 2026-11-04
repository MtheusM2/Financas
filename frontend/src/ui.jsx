import { useId, useMemo, useState } from "react";
import { z } from "zod";
import { money, parseMoney, today, toInputMoney } from "./format";

export function Tile({ label, value, hint, tone, to }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`value ${tone || ""}`}>{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

export function Status({ level, children }) {
  const map = { cabe: ["good", "✓ Cabe"], atencao: ["warn", "! Atenção"], compromete: ["bad", "✕ Compromete"], info: ["good", "i"], feito: ["good", "✓"] };
  const [kind, label] = map[level] || map.info;
  return <div className={`status ${kind}`} role="status"><span className="icon">{label}</span><div>{children}</div></div>;
}

export function Progress({ value, tone }) {
  return <div className="bar" role="progressbar" aria-valuenow={Math.round(value)}><div style={{ width: `${Math.min(value, 100)}%`, background: tone }} /></div>;
}

export function Loading({ state, children }) {
  if (state.error && state.data === undefined) return <div className="error-box" role="alert">{state.error.message}</div>;
  if (state.data === undefined) return <p className="muted">Carregando…</p>;
  return children(state.data);
}

export function Empty({ children }) { return <p className="muted">{children}</p>; }

/* Validacao por tipo de campo: filtra os dados antes de sair do navegador. */
const text = (f) => {
  const base = z.string().trim().max(f.max || 200, "Texto longo demais.");
  return f.required ? base.min(1, "Preencha este campo.") : base;
};

const VALIDATORS = {
  text,
  password: (f) => z.string().min(f.min || 1, f.min ? `Use ao menos ${f.min} caracteres.` : "Preencha este campo."),
  email: () => z.string().trim().email("E-mail inválido."),
  code: () => z.string().trim().regex(/^\d{6}$/, "Use os 6 dígitos do código."),
  date: (f) => (f.required ? z.string().regex(/^\d{4}-\d{2}-\d{2}$/, "Informe a data.") : z.string()),
  month: (f) => (f.required ? z.string().regex(/^\d{4}-\d{2}$/, "Informe o mês.") : z.string()),
  select: (f) => (f.required ? z.string().min(1, "Escolha uma opção.") : z.string()),
  check: () => z.boolean(),
  money: (f) => z.string().transform((value, ctx) => {
    const cents = parseMoney(value);
    if (cents === null) {
      if (f.required) ctx.addIssue({ code: "custom", message: "Informe o valor." });
      return null;
    }
    if (Number.isNaN(cents)) { ctx.addIssue({ code: "custom", message: "Valor inválido. Exemplo: 1.234,56" }); return null; }
    if (f.required && cents <= 0) { ctx.addIssue({ code: "custom", message: "O valor precisa ser maior que zero." }); return null; }
    return cents;
  }),
  integer: (f) => z.string().transform((value, ctx) => {
    if (!value.trim()) {
      if (f.required) ctx.addIssue({ code: "custom", message: "Preencha este campo." });
      return null;
    }
    const n = Number(value);
    const min = f.min ?? 0;
    if (!Number.isInteger(n) || n < min || (f.maxValue && n > f.maxValue)) {
      ctx.addIssue({ code: "custom", message: f.maxValue ? `Use um número de ${min} a ${f.maxValue}.` : `Use um número inteiro a partir de ${min}.` });
      return null;
    }
    return n;
  }),
  percent: (f) => z.string().transform((value, ctx) => {
    const raw = value.trim().replace(",", ".");
    if (!raw) {
      if (f.required) ctx.addIssue({ code: "custom", message: "Preencha este campo." });
      return "0";
    }
    if (!/^\d+(\.\d+)?$/.test(raw)) { ctx.addIssue({ code: "custom", message: "Número inválido." }); return "0"; }
    return raw;
  }),
};

function initialValue(field, initial) {
  const value = initial?.[field.name] ?? field.value;
  if (field.type === "check") return !!value;
  if (field.type === "money") return typeof value === "number" ? toInputMoney(value) : value ?? "";
  if (field.type === "date") return value ?? (field.required ? today() : "");
  return value === undefined || value === null ? "" : String(value);
}

/**
 * Formulario a partir de uma lista de campos. Valida no navegador com Zod e
 * entrega os valores ja convertidos (dinheiro em centavos).
 */
export function Form({ fields, initial, submit = "Salvar", onSubmit, onChange, children, resetOnSuccess = true, secondary }) {
  const visible = fields.filter(Boolean);
  const schema = useMemo(() => z.object(Object.fromEntries(visible.map((f) => [f.name, VALIDATORS[f.type || "text"](f)]))), [visible.map((f) => f.name + f.type).join()]);
  const start = () => Object.fromEntries(visible.map((f) => [f.name, initialValue(f, initial)]));
  const [values, setValues] = useState(start);
  const [errors, setErrors] = useState({});
  const [failure, setFailure] = useState(null);
  const [busy, setBusy] = useState(false);

  const set = (name, value) => {
    const next = { ...values, [name]: value };
    setValues(next);
    setErrors({ ...errors, [name]: undefined });
    onChange?.(next);
  };

  const handle = async (event) => {
    event.preventDefault();
    const current = Object.fromEntries(visible.map((f) => [f.name, values[f.name] ?? initialValue(f, initial)]));
    const parsed = schema.safeParse(current);
    if (!parsed.success) {
      setErrors(Object.fromEntries(parsed.error.issues.map((i) => [i.path[0], i.message])));
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      await onSubmit(parsed.data);
      if (resetOnSuccess) setValues(start());
    } catch (error) {
      setFailure(error.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={handle} noValidate>
      <div className="form-grid">
        {visible.map((f) => <Field key={f.name} field={f} value={values[f.name] ?? initialValue(f, initial)} error={errors[f.name]} onChange={(v) => set(f.name, v)} />)}
      </div>
      {children}
      {failure && <div className="error-box" role="alert">{failure}</div>}
      <div className="row" style={{ marginTop: 10 }}>
        <button className="primary" disabled={busy} type="submit">{busy ? "Aguarde…" : submit}</button>
        {secondary}
      </div>
    </form>
  );
}

function Field({ field, value, error, onChange }) {
  const id = useId();
  const type = field.type || "text";
  if (type === "check") {
    return (
      <label className="field check">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        <span>{field.label}</span>
      </label>
    );
  }
  const common = {
    id, value, "aria-invalid": !!error, "aria-describedby": field.help || error ? `${id}-nota` : undefined,
    onChange: (e) => onChange(e.target.value),
  };
  let input;
  if (type === "select") {
    input = (
      <select {...common}>
        {field.placeholder !== false && <option value="">{field.placeholder || "Escolha…"}</option>}
        {field.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  } else if (type === "money" || type === "percent") {
    input = <input {...common} inputMode="decimal" placeholder={field.placeholder || (type === "money" ? "0,00" : "0")} />;
  } else if (type === "integer" || type === "code") {
    input = <input {...common} inputMode="numeric" autoComplete={type === "code" ? "one-time-code" : undefined} placeholder={field.placeholder} />;
  } else {
    input = <input {...common} type={type} autoComplete={field.autoComplete} placeholder={field.placeholder} />;
  }
  return (
    <div className="field">
      <label htmlFor={id}>{field.label}</label>
      {input}
      <div id={`${id}-nota`}>
        {field.help && <div className="help">{field.help}</div>}
        {error && <div className="error">{error}</div>}
      </div>
    </div>
  );
}

export function Foldout({ label, children }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" className="small" aria-expanded={open} onClick={() => setOpen(!open)}>{open ? "Fechar" : label}</button>
      {open && <div style={{ marginTop: 10 }}>{children(() => setOpen(false))}</div>}
    </div>
  );
}

export function ResultValue({ value }) {
  return <span className={value > 0 ? "pos" : value < 0 ? "neg" : ""}>{money(value)}</span>;
}
