// Shared UI building blocks (flat cards, chips, buttons, form fields, dialogs, states).
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import {
  LuChevronDown, LuChevronLeft, LuChevronRight, LuCircleAlert, LuFlaskConical, LuInbox, LuLoaderCircle, LuRefreshCw, LuX,
} from "react-icons/lu";
import type { ApiError } from "../api/client";
import { fmtNum, humanize } from "../lib/format";
import { Link } from "../lib/router";
import { bureauColor } from "../lib/theme";

const cx = (...xs: Array<string | false | null | undefined>) => xs.filter(Boolean).join(" ");
export { cx };

// ----------------------------------------------------------------------------- layout
export function Card(props: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children?: ReactNode;
  className?: string; bodyClassName?: string; id?: string; tone?: "default" | "tint" | "alert" }) {
  const { title, subtitle, actions, children, className, bodyClassName, id, tone = "default" } = props;
  return (
    <section id={id} className={cx("min-w-0 rounded-lg border print-break-avoid",
      tone === "alert" ? "border-red/60 bg-red-soft" : tone === "tint" ? "border-line bg-tint" : "border-line bg-white", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5 pb-2">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold text-navy-ink">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2 print:hidden">{actions}</div>}
        </header>
      )}
      <div className={cx("overflow-x-auto", title || actions ? "px-4 pb-4" : "p-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader(props: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; meta?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-navy-ink">{props.title}</h1>
        {props.subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{props.subtitle}</p>}
        {props.meta && <div className="mt-2 flex flex-wrap items-center gap-2">{props.meta}</div>}
      </div>
      {props.actions && <div className="flex flex-wrap items-center gap-2 print:hidden">{props.actions}</div>}
    </div>
  );
}

// ----------------------------------------------------------------------------- chips
export type Tone = "neutral" | "blue" | "orange" | "green" | "red" | "navy";
const TONE: Record<Tone, string> = {
  neutral: "bg-slate-soft text-slate-ink border-line",
  blue: "bg-blue-soft text-blue-ink border-blue/30",
  orange: "bg-orange-soft text-orange-ink border-orange/40",
  green: "bg-green-soft text-green-ink border-green/30",
  red: "bg-red-soft text-red-ink border-red/40",
  navy: "bg-navy-soft text-navy-ink border-navy/25",
};

export function Chip(props: { tone?: Tone; icon?: ReactNode; children: ReactNode; title?: string; className?: string; wrap?: boolean }) {
  return (
    <span title={props.title} className={cx("inline-flex max-w-full items-center gap-1 border px-2 py-0.5 text-xs font-medium",
      props.wrap ? "rounded-xl text-left whitespace-normal" : "rounded-full whitespace-nowrap", TONE[props.tone ?? "neutral"], props.className)}>
      {props.icon}
      <span className={props.wrap ? "" : "truncate"}>{props.children}</span>
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  RECEIVED: "blue", PENDING: "orange", UNDER_PROCESS: "blue", TRANSFERRED: "neutral", ESCALATED: "navy", DISPOSED: "green",
};
const STATUS_TEXT: Record<string, string> = {
  RECEIVED: "Received", PENDING: "Pending", UNDER_PROCESS: "Under process", TRANSFERRED: "Transferred",
  ESCALATED: "Escalated", DISPOSED: "Disposed",
};
export const StatusChip = ({ status }: { status: string }) => (
  <Chip tone={STATUS_TONE[status] ?? "neutral"}>{STATUS_TEXT[status] ?? humanize(status)}</Chip>
);

const BAND_TONE: Record<string, Tone> = { CRITICAL: "red", HIGH: "orange", MEDIUM: "blue", LOW: "neutral" };
export function BandChip({ band, score, overridden }: { band: string | null | undefined; score?: number | null; overridden?: boolean }) {
  if (!band) return <span className="text-muted">—</span>;
  return (
    <Chip tone={BAND_TONE[band] ?? "neutral"} title={overridden ? "Priority band overridden by an officer" : undefined}>
      {humanize(band)}{score !== undefined && score !== null ? ` ${score.toFixed(0)}` : ""}{overridden ? " (override)" : ""}
    </Chip>
  );
}

const TIER_TONE: Record<string, Tone> = { DUPLICATE: "green", RELATED: "orange", CONFLICT: "red" };
export const TierChip = ({ tier }: { tier: string }) => <Chip tone={TIER_TONE[tier] ?? "neutral"}>{humanize(tier)}</Chip>;

const RISK_TONE: Record<string, Tone> = { HIGH: "red", ELEVATED: "orange", NORMAL: "green" };
export function RiskChip({ band, score }: { band: string | null | undefined; score?: number | null }) {
  if (!band) return <span className="text-muted">—</span>;
  return <Chip tone={RISK_TONE[band] ?? "neutral"}>{humanize(band)}{score !== undefined && score !== null ? ` ${score.toFixed(0)}` : ""}</Chip>;
}

export function BureauTag({ code, name }: { code: string | null | undefined; name?: string }) {
  if (!code) return <span className="text-muted">—</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink" title={name}>
      <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: bureauColor(code) }} />
      {code}
    </span>
  );
}

export function SyntheticBadge({ label = "Synthetic" }: { label?: string }) {
  return (
    <Chip tone="neutral" icon={<LuFlaskConical aria-hidden className="shrink-0" />}
      title="Generated demonstration data — not a real AICTE record">{label}</Chip>
  );
}

// ----------------------------------------------------------------------------- buttons
type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANT: Record<Variant, string> = {
  primary: "border-blue bg-blue text-white hover:bg-blue-ink",
  secondary: "border-line-strong bg-white text-navy-ink hover:bg-tint",
  danger: "border-red bg-red text-white hover:bg-red-ink",
  ghost: "border-transparent bg-transparent text-blue-ink hover:bg-blue-soft",
};

export function Button(props: { children?: ReactNode; onClick?: () => void; variant?: Variant; size?: "sm" | "md";
  icon?: ReactNode; disabled?: boolean; busy?: boolean; type?: "button" | "submit"; title?: string; className?: string;
  "aria-label"?: string; "aria-pressed"?: boolean }) {
  const { variant = "secondary", size = "md", busy, disabled, icon, children, type = "button", className, ...rest } = props;
  return (
    <button type={type} disabled={disabled || busy} onClick={props.onClick} title={rest.title} aria-label={rest["aria-label"]}
      aria-pressed={rest["aria-pressed"]}
      className={cx("inline-flex items-center justify-center gap-1.5 rounded-md border font-semibold transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-55", size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        VARIANT[variant], className)}>
      {busy ? <LuLoaderCircle className="animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function LinkButton(props: { to: string; children: ReactNode; icon?: ReactNode; variant?: Variant; size?: "sm" | "md" }) {
  const { variant = "secondary", size = "md" } = props;
  return (
    <Link to={props.to} className={cx("inline-flex items-center justify-center gap-1.5 rounded-md border font-semibold no-underline",
      size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm", VARIANT[variant])}>
      {props.icon}
      {props.children}
    </Link>
  );
}

// ----------------------------------------------------------------------------- form fields
export function Field(props: { label: ReactNode; children: (id: string) => ReactNode; hint?: ReactNode; error?: string | null;
  required?: boolean; className?: string }) {
  const id = useId();
  return (
    <div className={props.className}>
      <label htmlFor={id} className="mb-1 block text-xs font-semibold text-ink">
        {props.label}
        {props.required && <span className="text-red-ink" aria-hidden> *</span>}
      </label>
      {props.children(id)}
      {props.error ? <p className="mt-1 text-xs text-red-ink" role="alert">{props.error}</p>
        : props.hint ? <p className="mt-1 text-xs text-muted">{props.hint}</p> : null}
    </div>
  );
}

export function SelectInput(props: { id?: string; value: string; onChange: (v: string) => void; options: Array<{ value: string; label: string }>;
  placeholder?: string; disabled?: boolean; required?: boolean; className?: string; "aria-label"?: string; invalid?: boolean }) {
  return (
    <select id={props.id} value={props.value} disabled={props.disabled} required={props.required} aria-label={props["aria-label"]}
      aria-invalid={props.invalid || undefined} onChange={(e) => props.onChange(e.target.value)} className={cx("field-input", props.className)}>
      {props.placeholder !== undefined && <option value="">{props.placeholder}</option>}
      {props.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

/** Checkbox dropdown for multi-value filters. */
export function MultiSelect(props: { label: string; options: Array<{ value: string; label: string }>; value: string[];
  onChange: (v: string[]) => void; className?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e: globalThis.MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  const summary = props.value.length === 0 ? "All" : props.value.length <= 2
    ? props.value.map((v) => props.options.find((o) => o.value === v)?.label ?? v).join(", ") : `${props.value.length} selected`;
  const toggle = (v: string) => props.onChange(props.value.includes(v) ? props.value.filter((x) => x !== v) : [...props.value, v]);
  return (
    <div ref={box} className={cx("relative", props.className)}>
      <button type="button" aria-expanded={open} aria-haspopup="true" onClick={() => setOpen((o) => !o)}
        className={cx("field-input flex items-center justify-between gap-2 text-left", props.value.length ? "border-blue/60" : "")}>
        <span className="truncate"><span className="text-muted">{props.label}: </span>{summary}</span>
        <LuChevronDown aria-hidden className="shrink-0 text-muted" />
      </button>
      {open && (
        <div className="absolute z-30 mt-1 max-h-72 w-full min-w-56 overflow-auto rounded-md border border-line bg-white p-1 shadow-lg"
          role="group" aria-label={props.label}>
          {props.options.map((o) => (
            <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-tint">
              <input type="checkbox" checked={props.value.includes(o.value)} onChange={() => toggle(o.value)} />
              <span>{o.label}</span>
            </label>
          ))}
          {props.value.length > 0 && (
            <button type="button" onClick={() => props.onChange([])} className="mt-1 w-full rounded px-2 py-1 text-left text-xs text-blue-ink hover:bg-blue-soft">
              Clear {props.label.toLowerCase()}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------- dialogs
export function Modal(props: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode;
  size?: "md" | "lg"; description?: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    if (!props.open) return undefined;
    const previous = document.activeElement as HTMLElement | null;
    const first = panel.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])");
    (first ?? panel.current)?.focus();
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") props.onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.open]);
  if (!props.open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-ink/40 p-4 pt-[8vh] print:hidden"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) props.onClose();
      }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
        className={cx("w-full rounded-lg border border-line bg-white shadow-xl", props.size === "lg" ? "max-w-3xl" : "max-w-lg")}>
        <div className="flex items-start justify-between gap-3 rounded-t-lg bg-navy px-4 py-3">
          <h2 id={titleId} className="text-base font-semibold text-white">{props.title}</h2>
          <button type="button" data-close onClick={props.onClose} className="text-white/80 hover:text-white" aria-label="Close dialog">
            <LuX aria-hidden />
          </button>
        </div>
        <div className="px-4 py-4">
          {props.description && <div className="mb-3 text-sm text-muted">{props.description}</div>}
          {props.children}
        </div>
        {props.footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-3">{props.footer}</div>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- states
export function Loading({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cx("flex items-center gap-2 py-8 text-sm text-muted", className)} role="status">
      <LuLoaderCircle className="animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function ErrorState({ error, onRetry, className }: { error: ApiError | Error; onRetry?: () => void; className?: string }) {
  const status = "status" in error ? (error as ApiError).status : 0;
  const hint = status === 403 ? "Your current demo role does not have permission for this view. Switch role from the header."
    : status === 404 ? "The record does not exist or the link is out of date." : status === 0 ? "" : "";
  return (
    <div className={cx("flex items-start gap-3 rounded-lg border border-red/40 bg-red-soft px-4 py-3 text-sm", className)} role="alert">
      <LuCircleAlert className="mt-0.5 shrink-0 text-red-ink" aria-hidden />
      <div className="flex-1">
        <p className="font-semibold text-red-ink">{error.message}</p>
        {hint && <p className="mt-0.5 text-ink">{hint}</p>}
      </div>
      {onRetry && <Button size="sm" icon={<LuRefreshCw aria-hidden />} onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Empty({ title, children, action, className }: { title: string; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-col items-center gap-2 rounded-lg border border-dashed border-line-strong px-4 py-8 text-center", className)}>
      <LuInbox className="text-2xl text-slate" aria-hidden />
      <p className="font-semibold text-ink">{title}</p>
      {children && <div className="max-w-md text-sm text-muted">{children}</div>}
      {action}
    </div>
  );
}

export function InlineError({ error }: { error: ApiError | null | undefined }) {
  if (!error) return null;
  const fields = error.fieldErrors();
  const keys = Object.keys(fields);
  return (
    <div className="rounded-md border border-red/40 bg-red-soft px-3 py-2 text-sm text-red-ink" role="alert">
      <p className="font-semibold">{error.message}</p>
      {keys.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-xs">
          {keys.map((k) => <li key={k}>{k.startsWith("#") ? fields[k] : <><span className="font-semibold">{k}</span>: {fields[k]}</>}</li>)}
        </ul>
      )}
    </div>
  );
}

// ----------------------------------------------------------------------------- data display
export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <nav className="flex flex-wrap items-center justify-between gap-2 pt-3 text-sm text-muted print:hidden" aria-label="Pagination">
      <span className="num">{fmtNum(from)}–{fmtNum(to)} of {fmtNum(total)}</span>
      <div className="flex items-center gap-1">
        <Button size="sm" icon={<LuChevronLeft aria-hidden />} disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">
          Previous
        </Button>
        <span className="num px-2">Page {page} of {pages}</span>
        <Button size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">
          Next <LuChevronRight aria-hidden />
        </Button>
      </div>
    </nav>
  );
}

export function KeyValues({ items, cols = 2 }: { items: Array<[ReactNode, ReactNode]>; cols?: 1 | 2 | 3 }) {
  return (
    <dl className={cx("grid gap-x-6 gap-y-2.5 text-sm", cols === 3 ? "sm:grid-cols-3" : cols === 2 ? "sm:grid-cols-2" : "")}>
      {items.map(([k, v], i) => (
        <div key={i} className="min-w-0">
          <dt className="text-xs text-muted">{k}</dt>
          <dd className="mt-0.5 break-words text-ink">{v ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange, className }: { tabs: Array<{ value: T; label: ReactNode; count?: number }>;
  value: T; onChange: (v: T) => void; className?: string }) {
  return (
    <div role="tablist" className={cx("flex flex-wrap gap-1 border-b border-line", className)}>
      {tabs.map((t) => (
        <button key={t.value} type="button" role="tab" aria-selected={value === t.value} onClick={() => onChange(t.value)}
          className={cx("-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-semibold",
            value === t.value ? "border-blue text-blue-ink" : "border-transparent text-muted hover:text-ink")}>
          {t.label}
          {t.count !== undefined && <span className="num rounded-full bg-slate-soft px-1.5 text-xs text-slate-ink">{fmtNum(t.count)}</span>}
        </button>
      ))}
    </div>
  );
}

/** KPI tile in the PPT style: tinted card, large coloured figure, muted label. */
export function Kpi(props: { label: string; value: number | string; color: string; to?: string; hint?: string }) {
  const body = (
    <>
      <span className="num block text-[28px] leading-none font-bold" style={{ color: props.color }}>
        {typeof props.value === "number" ? fmtNum(props.value) : props.value}
      </span>
      <span className="mt-2 block text-sm text-muted">{props.label}</span>
      {props.hint && <span className="mt-0.5 block text-xs text-muted">{props.hint}</span>}
    </>
  );
  const cls = "block rounded-lg border border-[#d6e0f0] bg-tint px-4 py-3.5 no-underline";
  return props.to ? <Link to={props.to} className={cx(cls, "hover:border-blue/60")} title={`Open the ${props.label.toLowerCase()} cases`}>{body}</Link>
    : <div className={cls}>{body}</div>;
}

export function Meter({ value, max = 1, color, label }: { value: number; max?: number; color: string; label?: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-slate-soft" role="meter" aria-valuenow={value} aria-valuemin={0}
      aria-valuemax={max} aria-label={label}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export const Disclosure = ({ summary, children }: { summary: ReactNode; children: ReactNode }) => (
  <details className="group rounded-md border border-line bg-white">
    <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-semibold text-navy-ink">
      <LuChevronRight className="transition-transform group-open:rotate-90" aria-hidden /> {summary}
    </summary>
    <div className="border-t border-line px-3 py-2">{children}</div>
  </details>
);
