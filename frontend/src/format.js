const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const compact = new Intl.NumberFormat("pt-BR", { notation: "compact", maximumFractionDigits: 1 });

export const money = (cents) => (cents === null || cents === undefined ? "—" : currency.format(cents / 100));
export const moneyShort = (cents) => `R$ ${compact.format(cents / 100)}`;

// Aceita 1.234,56 ou 1234.56 ou 1234
export function parseMoney(text) {
  if (typeof text === "number") return Math.round(text * 100);
  const raw = String(text ?? "").replace(/[R$\s]/g, "");
  if (!raw) return null;
  const normalized = raw.includes(",") ? raw.replace(/\./g, "").replace(",", ".") : raw;
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return NaN;
  return Math.round(Number(normalized) * 100);
}

export const toInputMoney = (cents) => (cents === null || cents === undefined ? "" : (cents / 100).toFixed(2).replace(".", ","));

export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

export const dateBR = (iso) => (iso ? iso.slice(0, 10).split("-").reverse().join("/") : "—");

const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
export const monthName = (m) => MONTHS[m - 1];
export const monthLabel = (text) => {
  const [y, m] = String(text).split("-");
  return m ? `${MONTHS[Number(m) - 1]}/${y.slice(2)}` : y;
};

export const KINDS = {
  renda: "Salário/Renda",
  gasto: "Gasto",
  fora_escopo: "Fora do escopo",
  divida: "Dívida",
  investimento: "Investimento",
  guardado: "Guardado",
  lazer: "Lazer",
};
export const OUTFLOW_KINDS = ["gasto", "fora_escopo", "divida", "investimento", "guardado", "lazer"];
