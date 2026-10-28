// Demo session: the selected (simulated) role, its server-reported permissions and reference data.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, setDemoUser } from "../api/client";
import type { Bureau, CategoryRule, DemoUserOut, MeOut, OfficerRef, Reference, Region, StateRef, TrustRef } from "../api/models";

const STORAGE_KEY = "samanvay.demoUser";
const DEFAULT_USER = "competent.authority";

function storedUser(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || DEFAULT_USER;
  } catch {
    return DEFAULT_USER;
  }
}

export interface RefData {
  bureaus: Bureau[];
  regions: Region[];
  states: StateRef[];
  categories: CategoryRule[];
  officers: OfficerRef[];
  trusts: TrustRef[];
  statuses: Record<string, string>;
  outcomes: Record<string, string>;
  actionTypes: Record<string, string>;
  manualActions: string[];
  regulatoryActions: string[];
  channels: Record<string, string>;
  disclaimer: string;
  /** The application's date (server clock; frozen when SAMANVAY_TODAY is set). */
  today: string;
  bureauName: (code: string | null | undefined) => string;
  categoryLabel: (code: string | null | undefined) => string;
  regionName: (code: string | null | undefined) => string;
  actionLabel: (code: string | null | undefined) => string;
  statusLabel: (code: string | null | undefined) => string;
}

interface Session {
  userId: string;
  me: MeOut | null;
  users: DemoUserOut[];
  ref: RefData | null;
  /** Bumped whenever the role changes or data is mutated, so views refetch. */
  version: number;
  setUser: (id: string) => void;
  can: (permission: string) => boolean;
  bump: () => void;
  reloadReference: () => void;
  bootError: string | null;
}

const SessionContext = createContext<Session | null>(null);

function buildRef(r: Reference): RefData {
  const bureaus = r.bureaus as unknown as Bureau[];
  const categories = r.categories as unknown as CategoryRule[];
  const regions = r.regions as unknown as Region[];
  const bMap = new Map(bureaus.map((b) => [b.code, b.name]));
  const cMap = new Map(categories.map((c) => [c.code, c.label]));
  const rMap = new Map(regions.map((x) => [x.code, x.name]));
  return {
    bureaus, regions, categories,
    states: r.states as unknown as StateRef[],
    officers: r.officers as unknown as OfficerRef[],
    trusts: r.trusts as unknown as TrustRef[],
    statuses: r.statuses, outcomes: r.outcomes, actionTypes: r.action_types,
    manualActions: r.manual_actions, regulatoryActions: r.regulatory_actions, channels: r.channels,
    disclaimer: r.disclaimer, today: r.today,
    bureauName: (c) => (c ? bMap.get(c) ?? c : "—"),
    categoryLabel: (c) => (c ? cMap.get(c) ?? c : "—"),
    regionName: (c) => (c ? rMap.get(c) ?? c : "—"),
    actionLabel: (c) => (c ? r.action_types[c] ?? c.replace(/_/g, " ").toLowerCase() : "—"),
    statusLabel: (c) => (c ? r.statuses[c] ?? c : "—"),
  };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [userId, setUserId] = useState<string>(() => {
    const u = storedUser();
    setDemoUser(u);
    return u;
  });
  const [me, setMe] = useState<MeOut | null>(null);
  const [users, setUsers] = useState<DemoUserOut[]>([]);
  const [ref, setRef] = useState<RefData | null>(null);
  const [version, setVersion] = useState(0);
  const [bootError, setBootError] = useState<string | null>(null);

  const loadReference = useCallback(() => {
    api.get<Reference>("/api/system/reference").then((r) => setRef(buildRef(r))).catch((e: Error) => setBootError(e.message));
  }, []);

  useEffect(() => {
    api.get<DemoUserOut[]>("/api/system/users").then(setUsers).catch((e: Error) => setBootError(e.message));
    loadReference();
  }, [loadReference]);

  useEffect(() => {
    setDemoUser(userId);
    api.get<MeOut>("/api/system/me").then((m) => {
      setMe(m);
      setBootError(null);
    }).catch((e: Error) => {
      if (userId !== DEFAULT_USER) setUserId(DEFAULT_USER);
      else setBootError(e.message);
    });
  }, [userId]);

  const setUser = useCallback((id: string) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* storage unavailable: role lasts for this page view only */
    }
    setDemoUser(id);
    setUserId(id);
    setVersion((v) => v + 1);
  }, []);

  const value = useMemo<Session>(() => ({
    userId, me, users, ref, version, setUser, bootError,
    can: (p: string) => !!me?.permissions.includes(p),
    bump: () => setVersion((v) => v + 1),
    reloadReference: loadReference,
  }), [userId, me, users, ref, version, setUser, bootError, loadReference]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const s = useContext(SessionContext);
  if (!s) throw new Error("useSession must be used inside SessionProvider");
  return s;
}

/** Reference data; components render only after the app shell has loaded it. */
export function useRefData(): RefData {
  const { ref } = useSession();
  if (!ref) throw new Error("reference data not loaded");
  return ref;
}
