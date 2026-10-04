"use client";

import type { LoginResponse, Roles, User } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000/api/v1";

const TOKEN_KEY = "rahat.token";
const USER_KEY = "rahat.user";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getUser<T>(): T | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: unknown) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

async function request<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body, signal: init.signal ?? AbortSignal.timeout(60000) });
  if (res.status === 401 && path !== "/auth/login") {
    clearSession();
    window.dispatchEvent(new Event("rahat:session-expired"));
    throw new ApiError(401, "Session expired — sign in again.");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const msg =
      (data && typeof data === "object" && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : null) ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, json: unknown) =>
  request<T>(path, { method: "POST", json });

export async function login(
  username: string,
  password: string,
): Promise<User> {
  const res = await request<LoginResponse>("/auth/login", {
    method: "POST",
    json: { username, password },
  });
  const user: User = {
    username: res.username,
    display_name: res.display_name,
    role: res.role,
    role_label: res.role_label,
    perms: res.perms,
  };
  setSession(res.token, user);
  return user;
}

export const listRoles = () => request<Roles>("/auth/roles");

/** Live telemetry stream. Falls back to a polling ticker when WS is blocked. */
export function subscribeTelemetry(
  onMessage: (msg: Record<string, unknown>) => void,
  onState: (state: "connecting" | "live" | "polling" | "down") => void,
): () => void {
  const token = getToken();
  if (!token || typeof window === "undefined") return () => {};

  const wsUrl = `${API_BASE.replace(/^http/, "ws")}/ws/telemetry?token=${encodeURIComponent(token)}`;
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;

  const startPolling = () => {
    if (poll) return;
    onState("polling");
    poll = setInterval(() => {
      get<Record<string, unknown>>("/kpis")
        .then((k) => { onMessage({ kind: "kpi", kpis: k }); onState("polling"); })
        .catch(() => onState("down"));
    }, 5000);
  };

  const connect = () => {
    if (closed) return;
    onState("connecting");
    try {
      ws = new WebSocket(wsUrl);
    } catch {
      startPolling();
      return;
    }
    ws.onopen = () => {
      if (closed) return;
      if (poll) { clearInterval(poll); poll = null; }
      onState("live");
    };
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data as string));
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onerror = () => {
      /* onclose handles it */
    };
    ws.onclose = () => {
      if (closed) return;
      startPolling();
      retry = setTimeout(connect, 5000);
    };
  };

  // If the socket cannot open within 2.5s, degrade to polling rather than hang.
  const guard = setTimeout(() => {
    if (ws && ws.readyState !== WebSocket.OPEN) startPolling();
  }, 2500);

  connect();

  return () => {
    closed = true;
    clearTimeout(guard);
    if (retry) clearTimeout(retry);
    if (poll) clearInterval(poll);
    if (ws) {
      ws.onclose = null;
      ws.close();
    }
  };
}
