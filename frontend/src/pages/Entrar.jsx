import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Form, Status } from "../ui";

const EMAIL = { name: "email", type: "email", label: "E-mail", autoComplete: "username" };

function CodeTimer({ email, purpose, info, setInfo }) {
  const [left, setLeft] = useState(info.expira_em_segundos);
  const [message, setMessage] = useState(null);
  useEffect(() => { setLeft(info.expira_em_segundos); }, [info]);
  useEffect(() => {
    const timer = setInterval(() => setLeft((s) => Math.max(s - 1, 0)), 1000);
    return () => clearInterval(timer);
  }, []);

  const resend = async () => {
    setMessage(null);
    try {
      setInfo(await api("/autenticacao/reenviar", { method: "POST", body: { email, purpose } }));
    } catch (error) {
      const wait = error.detail?.aguarde_segundos;
      setMessage(wait ? `Limite de reenvios atingido. Tente de novo em ${Math.ceil(wait / 60)} min.` : error.message);
    }
  };

  return (
    <div style={{ marginTop: 10 }}>
      <p className="muted">
        {left > 0 ? `O código expira em ${left}s.` : "O código expirou. Peça um novo."} Reenvios restantes: {info.reenvios_restantes}.
      </p>
      <button type="button" className="small" onClick={resend} disabled={info.reenvios_restantes <= 0}>Reenviar código</button>
      {message && <div className="error-box" role="alert">{message}</div>}
    </div>
  );
}

export default function Entrar({ onLogin }) {
  const [mode, setMode] = useState("entrar");
  const [email, setEmail] = useState("");
  const [info, setInfo] = useState(null);
  const [needsTotp, setNeedsTotp] = useState(false);
  const [notice, setNotice] = useState(null);

  const go = (next) => { setMode(next); setNotice(null); };

  const screens = {
    entrar: (
      <>
        <h1>Entrar</h1>
        {notice && <Status level="info">{notice}</Status>}
        <Form
          key={needsTotp ? "totp" : "senha"} resetOnSuccess={false} submit="Entrar"
          fields={[EMAIL, { name: "password", type: "password", label: "Senha", autoComplete: "current-password" },
            needsTotp && { name: "totp", type: "code", label: "Código do app autenticador" }]}
          initial={{ email }}
          onSubmit={async (values) => {
            setEmail(values.email);
            try {
              onLogin(await api("/autenticacao/entrar", { method: "POST", body: values }));
            } catch (error) {
              if (error.detail === "codigo_2fa_necessario") { setNeedsTotp(true); throw new ApiError(401, "Informe o código do app autenticador."); }
              if (error.detail === "email_nao_confirmado") {
                setInfo(await api("/autenticacao/reenviar", { method: "POST", body: { email: values.email, purpose: "cadastro" } }));
                go("confirmar");
                return;
              }
              throw error;
            }
          }}
        />
        <div className="row" style={{ marginTop: 14 }}>
          <button type="button" className="small" onClick={() => go("cadastro")}>Criar conta</button>
          <button type="button" className="small" onClick={() => go("recuperar")}>Esqueci a senha</button>
        </div>
      </>
    ),
    cadastro: (
      <>
        <h1>Criar conta</h1>
        <p className="muted">Só e-mails autorizados podem se cadastrar.</p>
        <Form
          resetOnSuccess={false} submit="Enviar código"
          fields={[{ name: "name", label: "Nome", required: true, max: 80 }, EMAIL,
            { name: "password", type: "password", label: "Senha", min: 10, autoComplete: "new-password", help: "Mínimo de 10 caracteres." }]}
          onSubmit={async (values) => {
            setEmail(values.email);
            setInfo(await api("/autenticacao/cadastro", { method: "POST", body: values }));
            go("confirmar");
          }}
        />
        <button type="button" className="small" style={{ marginTop: 14 }} onClick={() => go("entrar")}>Já tenho conta</button>
      </>
    ),
    confirmar: (
      <>
        <h1>Confirme seu e-mail</h1>
        <p className="muted">Enviamos um código para {email}.</p>
        <Form
          submit="Confirmar" fields={[{ name: "code", type: "code", label: "Código" }]}
          onSubmit={async (values) => onLogin(await api("/autenticacao/verificar", { method: "POST", body: { email, code: values.code } }))}
        />
        {info && <CodeTimer email={email} purpose="cadastro" info={info} setInfo={setInfo} />}
      </>
    ),
    recuperar: (
      <>
        <h1>Recuperar senha</h1>
        <Form
          resetOnSuccess={false} submit="Enviar código" fields={[EMAIL]}
          onSubmit={async (values) => {
            setEmail(values.email);
            setInfo(await api("/autenticacao/recuperar", { method: "POST", body: values }));
            go("redefinir");
          }}
        />
        <button type="button" className="small" style={{ marginTop: 14 }} onClick={() => go("entrar")}>Voltar para entrar</button>
      </>
    ),
    redefinir: (
      <>
        <h1>Nova senha</h1>
        <p className="muted">Se {email} tiver cadastro, o código foi enviado.</p>
        <Form
          submit="Salvar senha"
          fields={[{ name: "code", type: "code", label: "Código" },
            { name: "password", type: "password", label: "Nova senha", min: 10, autoComplete: "new-password" }]}
          onSubmit={async (values) => {
            await api("/autenticacao/redefinir", { method: "POST", body: { email, ...values } });
            setMode("entrar");
            setNotice("Senha alterada. Entre com a nova senha.");
          }}
        />
        {info && <CodeTimer email={email} purpose="recuperacao" info={info} setInfo={setInfo} />}
      </>
    ),
  };

  return <div className="login"><div className="card">{screens[mode]}</div></div>;
}
