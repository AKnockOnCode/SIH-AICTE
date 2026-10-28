// Formatting helpers. Dates are shown in Indian Standard Time; numbers use Indian digit grouping.

const IST = "Asia/Kolkata";
const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric", timeZone: IST });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: IST,
});
const monthFmt = new Intl.DateTimeFormat("en-IN", { month: "short", year: "2-digit", timeZone: "UTC" });
const numFmt = new Intl.NumberFormat("en-IN");

/** A plain date ("2026-10-16") is a calendar date; a timestamp is converted to IST. */
export function fmtDate(value: string | null | undefined): string {
  if (!value) return "—";
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split("-").map(Number);
    return dateFmt.format(new Date(Date.UTC(y, m - 1, d, 6, 30)));
  }
  const t = new Date(value);
  return Number.isNaN(t.getTime()) ? value : dateFmt.format(t);
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const t = new Date(value);
  return Number.isNaN(t.getTime()) ? value : `${dateTimeFmt.format(t)} IST`;
}

export function fmtMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return monthFmt.format(new Date(Date.UTC(y, m - 1, 15)));
}

export const fmtNum = (n: number | null | undefined): string => (n === null || n === undefined ? "—" : numFmt.format(n));

export function fmtPct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtSigned(n: number, digits = 0): string {
  const s = n.toFixed(digits);
  return n > 0 ? `+${s}` : s;
}

export function daysLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return "—";
  if (days === 0) return "due today";
  return days > 0 ? `${days} day${days === 1 ? "" : "s"} left` : `${-days} day${days === -1 ? "" : "s"} overdue`;
}

export const humanize = (code: string | null | undefined): string =>
  code ? code.charAt(0).toUpperCase() + code.slice(1).toLowerCase().replace(/_/g, " ") : "—";

export function shortHash(h: string | null | undefined, n = 10): string {
  return h ? `${h.slice(0, n)}…` : "—";
}

export function plural(n: number, one: string, many?: string): string {
  return `${fmtNum(n)} ${n === 1 ? one : many ?? `${one}s`}`;
}

const DEMO_LABELS: Record<string, string> = {
  INSTITUTION_A: "Institution A", RISING_RISK: "Rising-risk institution", LIVE_TRIGGER: "Live conflict trigger",
  FLAGGED_TRUST: "Trust with several flagged institutions",
};
export const demoLabel = (tag: string | null | undefined): string => (tag ? DEMO_LABELS[tag] ?? humanize(tag) : "");

const ROLE_LABELS: Record<string, string> = {
  COMPETENT_AUTHORITY: "Competent Authority", RB_OFFICER: "RB Officer", PGRC_OFFICER: "PGRC Officer", REGIONAL_OFFICE: "Regional Office",
  SENIOR_MANAGEMENT: "Senior Management", SYSTEM: "System", OFFICER: "Officer",
};
export const roleLabel = (role: string | null | undefined): string => (role ? ROLE_LABELS[role] ?? humanize(role) : "—");
