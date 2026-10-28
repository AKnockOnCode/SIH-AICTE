// App shell: PPT-style navy title bar ("SAMANVAY | page | context"), role switcher, navigation.
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  LuBell, LuBuilding2, LuChartColumn, LuClipboardList, LuFilePlus, LuFileUp, LuFlaskConical, LuGitCompareArrows, LuLayoutDashboard,
  LuMenu, LuNetwork, LuNewspaper, LuSearch, LuShieldCheck, LuSlidersHorizontal, LuTriangleAlert, LuUserCheck, LuX,
} from "react-icons/lu";
import type { AlertPage } from "../api/models";
import { useApi } from "../lib/hooks";
import { Link, navigate, useLocation } from "../lib/router";
import { useSession } from "../lib/session";
import { useToast } from "../lib/toast";
import { cx } from "./ui";

// ----------------------------------------------------------------------------- page title context
const TitleCtx = createContext<(parts: string[]) => void>(() => undefined);

/** Set the title-bar text, e.g. useTitle("Case Workflow", "PGRC-5530"). */
export function useTitle(...parts: Array<string | null | undefined>) {
  const set = useContext(TitleCtx);
  const clean = parts.filter((p): p is string => !!p);
  const key = clean.join("|");
  useEffect(() => {
    set(clean);
    document.title = `${clean.join(" | ")} | AgniDrishti`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

const NAV: Array<{ group: string; items: Array<{ to: string; label: string; icon: ReactNode; match?: (p: string) => boolean }> }> = [
  { group: "Monitor", items: [
    { to: "/", label: "Command dashboard", icon: <LuLayoutDashboard />, match: (p) => p === "/" },
    { to: "/watchlist", label: "Watch-list", icon: <LuTriangleAlert /> },
    { to: "/overlaps", label: "Overlaps & conflicts", icon: <LuGitCompareArrows />, match: (p) => p.startsWith("/overlaps") || p.startsWith("/master-cases") },
    { to: "/alerts", label: "Alerts", icon: <LuBell /> },
  ] },
  { group: "Cases", items: [
    { to: "/search", label: "Search cases", icon: <LuSearch />, match: (p) => p === "/search" || (p.startsWith("/cases/") && p !== "/cases/new") },
    { to: "/cases/new", label: "New complaint", icon: <LuFilePlus /> },
    { to: "/match-reviews", label: "Match review", icon: <LuUserCheck /> },
  ] },
  { group: "Institutions", items: [
    { to: "/institutions", label: "Institutions", icon: <LuBuilding2 /> },
    { to: "/graph", label: "Trust / society graph", icon: <LuNetwork /> },
    { to: "/signals", label: "Public signals", icon: <LuNewspaper /> },
  ] },
  { group: "Analyse & administer", items: [
    { to: "/reports", label: "Reports", icon: <LuChartColumn /> },
    { to: "/imports", label: "Data import", icon: <LuFileUp /> },
    { to: "/rules", label: "Priority rules", icon: <LuSlidersHorizontal /> },
    { to: "/audit", label: "Audit & system status", icon: <LuShieldCheck /> },
  ] },
];

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  const { pathname } = useLocation();
  return (
    <nav aria-label="Main" className="space-y-5">
      {NAV.map((g) => (
        <div key={g.group}>
          <p className="px-3 pb-1.5 text-xs font-semibold text-muted">{g.group}</p>
          <ul className="space-y-0.5">
            {g.items.map((it) => {
              const active = it.match ? it.match(pathname) : pathname === it.to || pathname.startsWith(`${it.to}/`);
              return (
                <li key={it.to}>
                  <Link to={it.to} onClick={onNavigate} aria-current={active ? "page" : undefined}
                    className={cx("flex items-center gap-2.5 rounded-md px-3 py-1.5 text-sm no-underline",
                      active ? "bg-blue-soft font-semibold text-blue-ink" : "text-ink hover:bg-tint")}>
                    <span aria-hidden className={cx("text-base", active ? "text-blue" : "text-slate-ink")}>{it.icon}</span>
                    {it.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function RoleSwitcher() {
  const { users, userId, setUser, me } = useSession();
  const toast = useToast();
  return (
    <div className="flex items-center gap-2">
      <label htmlFor="demo-role" className="hidden text-xs text-white/75 lg:block">
        Demo role <span className="text-white/55">(simulated sign-in)</span>
      </label>
      <select id="demo-role" value={userId} title={me?.notice}
        onChange={(e) => {
          setUser(e.target.value);
          const u = users.find((x) => x.id === e.target.value);
          toast.push(`Now acting as ${u?.display_name ?? e.target.value}. Permissions are enforced by the server.`, "info");
        }}
        className="max-w-[40vw] rounded-md border border-white/25 bg-navy-ink px-1.5 py-1.5 text-xs text-white sm:max-w-none sm:px-2 sm:text-sm">
        {users.map((u) => <option key={u.id} value={u.id}>{u.role_label}{u.region_code ? ` (${u.region_code.charAt(0)}${u.region_code.slice(1).toLowerCase()})` : ""}</option>)}
      </select>
    </div>
  );
}

function AlertBell() {
  const { can } = useSession();
  const { data } = useApi<AlertPage>(can("alert.view") ? "/api/alerts" : null, { state: ["NEW"], page_size: 1 });
  const n = data?.total ?? 0;
  return (
    <Link to="/alerts?state=NEW" className="relative rounded-md p-2 text-white hover:bg-white/10" aria-label={`Alerts: ${n} new`}>
      <LuBell aria-hidden className="text-lg" />
      {n > 0 && (
        <span className="num absolute -top-0.5 -right-0.5 min-w-5 rounded-full bg-red px-1 text-center text-[10px] leading-5 font-bold text-white">
          {n > 999 ? "999+" : n}
        </span>
      )}
    </Link>
  );
}

function HeaderSearch() {
  const { params, pathname } = useLocation();
  const [q, setQ] = useState(pathname === "/search" ? params.get("q") ?? "" : "");
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    navigate(`/search?q=${encodeURIComponent(q.trim())}`);
  };
  return (
    <form role="search" onSubmit={submit} className="relative hidden w-full max-w-sm md:block">
      <LuSearch aria-hidden className="absolute top-1/2 left-2.5 -translate-y-1/2 text-white/60" />
      <input value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search institutions, aliases, Permanent IDs or case IDs"
        placeholder="Institution, alias, Permanent ID or case ID"
        className="w-full rounded-md border border-white/20 bg-white/10 py-1.5 pr-3 pl-8 text-sm text-white placeholder:text-white/55 focus:bg-white focus:text-ink focus:placeholder:text-muted" />
    </form>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [title, setTitle] = useState<string[]>([]);
  const [menu, setMenu] = useState(false);
  const { me, ref } = useSession();
  const mixed = !!ref?.disclaimer.startsWith("MIXED");
  return (
    <TitleCtx.Provider value={setTitle}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 bg-navy text-white print:hidden">
        <div className="flex h-14 items-center gap-3 px-3 sm:px-4">
          <button type="button" className="rounded-md p-2 hover:bg-white/10 lg:hidden" aria-label="Open navigation" onClick={() => setMenu(true)}>
            <LuMenu aria-hidden className="text-lg" />
          </button>
          <Link to="/" className="flex shrink-0 items-baseline gap-2 text-white no-underline" aria-label="AgniDrishti home">
            <span className="text-[17px] font-bold tracking-wide">AgniDrishti</span>
            <span className="hidden text-xs text-white/60 sm:inline" lang="hi">अग्निदृष्टि</span>
          </Link>
          <p className="hidden min-w-0 truncate text-[15px] font-semibold text-white/95 sm:block">
            {title.map((t, i) => <span key={i}><span className="titlebar-sep" aria-hidden>|</span>{t}</span>)}
          </p>
          <div className="ml-auto flex items-center gap-2">
            <HeaderSearch />
            <AlertBell />
            <RoleSwitcher />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 border-t border-white/10 bg-[#17294a] px-4 py-1 text-xs text-white/80">
          <LuFlaskConical aria-hidden className="shrink-0" />
          {mixed
            ? <span><strong className="text-white">Mixed data.</strong> Synthetic demo records (generated — not real AICTE records or findings) plus records entered or imported here; check each record's provenance.</span>
            : <span><strong className="text-white">Synthetic demo data.</strong> Institutions, complaints, officers and outcomes are generated — not real AICTE records or findings.</span>}
          <span className="text-white/60">Acting as {me?.user.display_name ?? "…"} (role simulation, not authentication).</span>
        </div>
      </header>
      {menu && (
        <div className="fixed inset-0 z-40 bg-ink/40 lg:hidden print:hidden" onMouseDown={(e) => {
          if (e.target === e.currentTarget) setMenu(false);
        }}>
          <div className="h-full w-72 overflow-y-auto bg-white p-3 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <span className="font-bold text-navy-ink">Menu</span>
              <button type="button" onClick={() => setMenu(false)} aria-label="Close navigation" className="rounded p-1 hover:bg-tint">
                <LuX aria-hidden />
              </button>
            </div>
            <NavList onNavigate={() => setMenu(false)} />
          </div>
        </div>
      )}
      <div className="mx-auto flex w-full max-w-[1600px]">
        <aside className="sticky top-[84px] hidden h-[calc(100vh-84px)] w-60 shrink-0 overflow-y-auto border-r border-line bg-white px-2 py-4 lg:block print:hidden">
          <NavList />
          <div className="mt-6 border-t border-line px-3 pt-3 text-xs text-muted">
            <LuClipboardList aria-hidden className="mr-1 inline" />
            Smart India Hackathon 2026 prototype for PS SIH26264.{" "}
            <a href="/api/docs" target="_blank" rel="noreferrer">API docs</a>
          </div>
        </aside>
        <main id="main" className="min-w-0 flex-1 px-4 py-5 sm:px-6 print:p-0">{children}</main>
      </div>
    </TitleCtx.Provider>
  );
}
