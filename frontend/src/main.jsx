import { createContext, lazy, Suspense, useContext, useEffect, useLayoutEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation, useNavigate, useNavigationType } from "react-router-dom";
import { api, clearCache, setUnauthorizedHandler, useApi } from "./api";
import { monthName } from "./format";
import "./styles.css";

// Cada tela so e carregada quando aberta; as ja abertas ficam no cache do navegador.
const Entrar = lazy(() => import("./pages/Entrar"));
const Painel = lazy(() => import("./pages/Painel"));
const Lancamentos = lazy(() => import("./pages/Lancamentos"));
const Compromissos = lazy(() => import("./pages/Compromissos"));
const Investimentos = lazy(() => import("./pages/Investimentos"));
const Objetivos = lazy(() => import("./pages/Objetivos"));
const Desafios = lazy(() => import("./pages/Desafios"));
const Relatorios = lazy(() => import("./pages/Relatorios"));
const Ajustes = lazy(() => import("./pages/Ajustes"));
const Planejamento = lazy(() => import("./pages/Planejamento"));
const Conciliacao = lazy(() => import("./pages/Conciliacao"));
const Holerites = lazy(() => import("./pages/Holerites"));

const MENU = [
  { to: "/", label: "Painel", module: "painel" },
  { to: "/lancamentos", label: "Lançamentos" },
  { to: "/conciliacao", label: "Importar e conciliar", module: "conciliacao" },
  { to: "/holerites", label: "Holerites", module: "holerites" },
  { to: "/planejamento", label: "Previsão e tetos", modules: ["previsao", "orcamento"] },
  { to: "/compromissos", label: "Dívidas e financiamentos", modules: ["dividas", "financiamentos"] },
  { to: "/investimentos", label: "Investimentos e reserva", modules: ["investimentos", "reserva"] },
  { to: "/objetivos", label: "Objetivos", module: "objetivos" },
  { to: "/desafios", label: "Desafios", module: "desafios" },
  { to: "/relatorios", label: "Relatórios", module: "relatorios" },
  { to: "/ajustes", label: "Ajustes" },
];

const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);

/* Pilha de navegacao: o que foi aberto, com a rolagem de cada tela. Os filtros ficam na URL. */
function loadStack() {
  try { return JSON.parse(sessionStorage.getItem("pilha")) || []; } catch { return []; }
}

function useNavigationStack() {
  const location = useLocation();
  const type = useNavigationType();
  const navigate = useNavigate();
  const [stack, setStack] = useState(loadStack);

  useLayoutEffect(() => {
    const path = location.pathname + location.search;
    setStack((old) => {
      let next;
      const position = old.findLastIndex((e) => e.key === location.key);
      if (position >= 0) next = old.slice(0, position + 1);
      else if (type === "REPLACE") next = [...old.slice(0, -1), { key: location.key, path }];
      else next = [...old, { key: location.key, path }];
      try { sessionStorage.setItem("pilha", JSON.stringify(next)); } catch { /* armazenamento indisponivel */ }
      return next;
    });
    let saved = 0;
    try { saved = Number(sessionStorage.getItem(`rolagem:${location.key}`)) || 0; } catch { /* idem */ }
    // Aguarda a tela desenhar para voltar ao mesmo ponto.
    requestAnimationFrame(() => window.scrollTo(0, type === "POP" ? saved : 0));
    return () => {
      try { sessionStorage.setItem(`rolagem:${location.key}`, String(window.scrollY)); } catch { /* idem */ }
    };
  }, [location.key]);

  return {
    canGoBack: stack.length > 1,
    back: () => navigate(-1),
    home: () => {
      setStack([]);
      navigate("/");
    },
  };
}

function Layout({ children, modules }) {
  const app = useApp();
  const location = useLocation();
  const stack = useNavigationStack();
  const [menu, setMenu] = useState(false);
  useEffect(() => setMenu(false), [location.key]);

  const items = MENU.filter((m) => {
    if (m.module) return modules.includes(m.module);
    if (m.modules) return m.modules.some((x) => modules.includes(x));
    return true;
  });
  const years = useMemo(() => {
    const now = new Date().getFullYear();
    return Array.from({ length: 8 }, (_, i) => now + 1 - i);
  }, []);

  return (
    <div className="shell">
      <nav className={`side ${menu ? "open" : ""}`} aria-label="Menu">
        <div className="brand">Finanças do Casal</div>
        {items.map((m) => <NavLink key={m.to} to={m.to} end={m.to === "/"}>{m.label}</NavLink>)}
        <button type="button" style={{ width: "100%", marginTop: 12 }} onClick={app.logout}>Sair ({app.user.nome})</button>
      </nav>
      <main className="main">
        <div className="topbar">
          <button type="button" className="menu-button" onClick={() => setMenu(!menu)} aria-expanded={menu}>Menu</button>
          <button type="button" onClick={stack.back} disabled={!stack.canGoBack}>Voltar</button>
          <button type="button" onClick={stack.home}>Início</button>
          <span className="grow" />
          <select aria-label="Ver dados de" value={app.scope} onChange={(e) => app.setScope(e.target.value)}>
            <option value="casal">Casal (somado)</option>
            {app.users.map((u) => <option key={u.id} value={`pessoa:${u.id}`}>{u.nome}</option>)}
            {app.accounts.map((a) => <option key={a.id} value={`conta:${a.id}`}>{a.nome}</option>)}
          </select>
          <select aria-label="Mês" value={app.period.mes} onChange={(e) => app.setPeriod({ ...app.period, mes: Number(e.target.value) })}>
            {Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{monthName(i + 1)}</option>)}
          </select>
          <select aria-label="Ano" value={app.period.ano} onChange={(e) => app.setPeriod({ ...app.period, ano: Number(e.target.value) })}>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </div>
        {children}
      </main>
    </div>
  );
}

function Authenticated({ user, setUser, modules }) {
  const users = useApi("/autenticacao/usuarios");
  const accounts = useApi("/contas");
  const [scope, setScopeState] = useState(user.preferencias?.escopo || "casal");
  const [period, setPeriod] = useState(() => {
    const now = new Date();
    return { ano: now.getFullYear(), mes: now.getMonth() + 1 };
  });

  const value = {
    user, setUser, scope, period, setPeriod, modules,
    users: users.data || [],
    accounts: (accounts.data || []).filter((a) => !a.arquivada),
    reloadAccounts: accounts.reload,
    setScope: (next) => {
      setScopeState(next);
      api("/autenticacao/preferencias", { method: "PATCH", body: { escopo: next } }).catch(() => {});
    },
    logout: async () => {
      await api("/autenticacao/sair", { method: "POST" }).catch(() => {});
      clearCache();
      setUser(null);
    },
  };

  return (
    <AppContext.Provider value={value}>
      <Layout modules={modules}>
        <Suspense fallback={<p className="muted">Carregando…</p>}>
          <Routes>
            <Route path="/" element={modules.includes("painel") ? <Painel /> : <Navigate to="/lancamentos" replace />} />
            <Route path="/lancamentos" element={<Lancamentos />} />
            <Route path="/conciliacao" element={<Conciliacao />} />
            <Route path="/holerites" element={<Holerites />} />
            <Route path="/planejamento" element={<Planejamento />} />
            <Route path="/compromissos" element={<Compromissos />} />
            <Route path="/investimentos" element={<Investimentos />} />
            <Route path="/objetivos" element={<Objetivos />} />
            <Route path="/desafios" element={<Desafios />} />
            <Route path="/relatorios" element={<Relatorios />} />
            <Route path="/ajustes" element={<Ajustes />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </Layout>
    </AppContext.Provider>
  );
}

/* Aba ou app aberto antes de uma atualizacao continua com o codigo antigo: aqui ele descobre a versao nova. */
function useNewVersion() {
  const [available, setAvailable] = useState(false);
  useEffect(() => {
    const current = document.querySelector('script[src*="/assets/index-"]')?.getAttribute("src");
    if (!current) return undefined;
    const check = async () => {
      if (document.visibilityState !== "visible") return;
      try {
        const html = await (await fetch("/", { cache: "no-store" })).text();
        const latest = html.match(/\/assets\/index-[^"']+\.js/);
        if (latest && latest[0] !== current) setAvailable(true);
      } catch { /* sem conexao: confere na proxima vez */ }
    };
    check();
    document.addEventListener("visibilitychange", check);
    const timer = setInterval(check, 5 * 60 * 1000);
    return () => { document.removeEventListener("visibilitychange", check); clearInterval(timer); };
  }, []);
  return available;
}

function UpdateBanner() {
  const available = useNewVersion();
  if (!available) return null;
  return (
    <div className="update-banner" role="status">
      <span>Há uma versão nova do sistema.</span>
      <button type="button" className="small" onClick={() => window.location.reload()}>Atualizar agora</button>
    </div>
  );
}

// Tela de uma versao que ja saiu do servidor: recarrega uma vez para pegar a atual.
window.addEventListener("vite:preloadError", (event) => {
  try {
    if (sessionStorage.getItem("recarregou")) return;
    sessionStorage.setItem("recarregou", "1");
  } catch { return; }
  event.preventDefault();
  window.location.reload();
});

function App() {
  const [user, setUser] = useState(undefined);
  const [modules, setModules] = useState(null);

  useEffect(() => {
    setUnauthorizedHandler(() => { clearCache(); setUser(null); });
    api("/modulos").then((d) => setModules(d.modulos)).catch(() => setModules([]));
    api("/autenticacao/eu").then(setUser).catch(() => setUser(null));
  }, []);

  if (user === undefined || modules === null) return <p className="muted" style={{ padding: 16 }}>Carregando…</p>;
  return (
    <BrowserRouter>
      <UpdateBanner />
      {user
        ? <Authenticated key={user.id} user={user} setUser={setUser} modules={modules} />
        : <Suspense fallback={null}><Entrar onLogin={setUser} /></Suspense>}
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")).render(<App />);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
