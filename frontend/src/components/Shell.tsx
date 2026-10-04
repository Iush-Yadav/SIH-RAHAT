"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { clearSession, getToken, getUser, subscribeTelemetry, get } from "@/lib/api";
import type { User, Health } from "@/lib/types";

export interface Session {
  user: User | null;
  login: (u: User) => void;
  logout: () => void;
}

const SessionCtx = createContext<Session>({
  user: null,
  login: () => {},
  logout: () => {},
});

export const useSession = () => useContext(SessionCtx);

interface TelemetryState {
  status: "connecting" | "live" | "polling" | "down" | "idle";
  ticks: number;
  last: Record<string, unknown> | null;
}

const TelemetryCtx = createContext<TelemetryState>({
  status: "idle",
  ticks: 0,
  last: null,
});

export const useTelemetry = () => useContext(TelemetryCtx);

export const NAV = [
  { href: "/", label: "War Room", key: "command" },
  { href: "/sim", label: "Mission Sim", key: "simulate" },
  { href: "/forecast", label: "Forecast", key: "forecast" },
  { href: "/planner", label: "Planner", key: "plan" },
  { href: "/inventory", label: "Stock & IoT", key: "inventory" },
  { href: "/resilience", label: "Resilience", key: "resilience" },
  { href: "/reports", label: "Briefing", key: "reports" },
  { href: "/admin", label: "Admin", key: "admin" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [health, setHealth] = useState<Health | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [tel, setTel] = useState<TelemetryState>({
    status: "idle",
    ticks: 0,
    last: null,
  });

  useEffect(() => {
    // localStorage only exists on the client — hydrate on mount, not during SSR.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUser(getUser<User>());
    setReady(true);
  }, []);

  const login = useCallback(
    (u: User) => {
      setUser(u);
      router.replace("/");
    },
    [router],
  );

  const logout = useCallback(() => {
    clearSession();
    setUser(null);
    router.replace("/login");
  }, [router]);

  useEffect(() => {
    window.addEventListener("rahat:session-expired", logout);
    return () => window.removeEventListener("rahat:session-expired", logout);
  }, [logout]);

  useEffect(() => {
    let alive = true;
    const check = () => get<Health>("/health").then(h => { if (alive) setHealth(h); }).catch(() => { if (alive) setHealth(null); });
    void check();
    const timer = setInterval(check, 15000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const authed = Boolean(getToken()) && user !== null;

  // Route guard
  useEffect(() => {
    if (!ready) return;
    if (pathname === "/login") {
      if (authed) router.replace("/");
      return;
    }
    if (!authed) router.replace("/login");
  }, [ready, authed, pathname, router]);

  // Telemetry stream, only while signed in.
  useEffect(() => {
    if (!authed) return;
    let n = 0;
    const stop = subscribeTelemetry(
      (msg) => {
        n += 1;
        setTel({ status: "live", ticks: n, last: msg });
      },
      (status) => setTel((t) => ({ ...t, status })),
    );
    return stop;
  }, [authed]);

  const session = useMemo<Session>(
    () => ({ user, login, logout }),
    [user, login, logout],
  );

  const isLogin = pathname === "/login";

  if (!ready) {
    // One hydration frame. Branded so a judge never sees a blank screen.
    return (
      <div className="grid-bg vignette flex min-h-screen items-center justify-center">
        <div className="text-center">
          <div className="text-lg font-bold tracking-[0.3em] text-fg">RAHAT</div>
          <div className="label mt-2 animate-pulse">
            establishing secure session…
          </div>
          <div className="mx-auto mt-4 h-[3px] w-40 overflow-hidden rounded bg-line">
            <div className="sweep h-full w-1/3 bg-cyan" />
          </div>
        </div>
      </div>
    );
  }

  if (!isLogin && !authed) return <div className="session-loading">Opening sign-in…</div>;

  if (isLogin) {
    return (
      <SessionCtx.Provider value={session}>
        <TelemetryCtx.Provider value={tel}>{children}</TelemetryCtx.Provider>
      </SessionCtx.Provider>
    );
  }

  const can = (k: string) => user?.perms.includes(k) ?? false;

  const activeNav = NAV.find(n => n.href === "/" ? pathname === "/" : pathname.startsWith(n.href));
  const restricted = pathname.startsWith("/admin") && !can("admin");

  return (
    <SessionCtx.Provider value={session}>
      <TelemetryCtx.Provider value={tel}>
        <div className="app-frame">
          <a href="#main-content" className="skip-link">Skip to content</a>
          <header className="masthead">
            <Link href="/" className="brand" aria-label="RAHAT home"><span className="brand-mark">r<span>↗</span></span><span>RAHAT<small>THE SUPPLY INTELLIGENCE PROJECT</small></span></Link>
            <div className="masthead-meta"><span className="edition">SIH 2026 / 26251</span><span className="demo-stamp">SYNTHETIC DEMO</span></div>
            <button className="btn mobile-menu" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen} aria-controls="main-navigation">{menuOpen ? "Close menu −" : "Menu +"}</button>
            <div className="account"><span className="avatar">{user?.display_name.slice(0, 1)}</span><span>{user?.display_name}<small>{user?.role_label}</small></span><button onClick={logout} className="signout" aria-label="Sign out">↗</button></div>
          </header>
          <nav id="main-navigation" aria-label="Main navigation" className={`main-navigation ${menuOpen ? "is-open" : ""}`}>
            {NAV.filter(n => n.key !== "admin" || can("admin")).map((n, i) => <Link key={n.href} href={n.href} onClick={() => setMenuOpen(false)} aria-current={activeNav?.href === n.href ? "page" : undefined} className={activeNav?.href === n.href ? "active" : ""}><span>{String(i + 1).padStart(2, "0")}</span>{n.label}</Link>)}
          </nav>
          <div className="system-strip"><span><i className={tel.status === "live" ? "status-dot online" : "status-dot"} />{tel.status === "live" ? "SIMULATED TELEMETRY CONNECTED" : `TELEMETRY · ${tel.status.toUpperCase()}`}</span><span>MODEL · {health?.model.status ?? "UNAVAILABLE"}</span><span className="strip-end">LOCAL DEMONSTRATION / GENERATED DATA</span></div>
          <main id="main-content" className="workspace">
            {restricted ? <section className="panel p-8"><h1>Administrator access required</h1><p className="mt-3 text-muted">Your role does not have access to account administration.</p><Link className="btn mt-5" href="/">Return to overview →</Link></section> : children}
          </main>
          <footer className="site-footer"><span><b>RAHAT</b> / Clarity across the supply chain.</span><span>Student prototype · Synthetic data · Human review required</span></footer>
        </div>
      </TelemetryCtx.Provider>
    </SessionCtx.Provider>
  );
}
