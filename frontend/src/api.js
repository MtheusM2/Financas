import { useCallback, useEffect, useState } from "react";

// Respostas ja vistas: a tela anterior reabre na hora e atualiza em seguida.
const cache = new Map();

export class ApiError extends Error {
  constructor(status, detail) {
    const text = typeof detail === "string" ? detail : detail?.mensagem;
    super(text || "Não foi possível concluir. Tente de novo.");
    this.status = status;
    this.detail = detail;
  }
}

function explain(detail) {
  // Erros de validacao do back-end chegam como lista.
  return Array.isArray(detail) ? "Confira os campos informados." : detail;
}

let onUnauthorized = () => {};
export const setUnauthorizedHandler = (fn) => { onUnauthorized = fn; };

export async function api(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      method,
      credentials: "same-origin",
      headers: { "X-Financas": "1", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Sem conexão com o sistema. Confira a VPN e se o PC está ligado.");
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/autenticacao/")) onUnauthorized();
    throw new ApiError(response.status, explain(data?.detail));
  }
  if (method !== "GET") cache.clear();
  return data;
}

export const clearCache = () => cache.clear();

export function useApi(path) {
  const [state, setState] = useState(() => ({ data: path ? cache.get(path) : undefined, error: null, loading: true }));

  const load = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api(path);
      cache.set(path, data);
      setState({ data, error: null, loading: false });
    } catch (error) {
      setState((old) => ({ ...old, error, loading: false }));
    }
  }, [path]);

  useEffect(() => {
    setState({ data: path ? cache.get(path) : undefined, error: null, loading: true });
    load();
  }, [path, load]);

  return { ...state, reload: load };
}

export function query(params) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}
