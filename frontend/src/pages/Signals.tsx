import type { ReactNode } from "react";
import { LuBadgeCheck, LuExternalLink, LuFlaskConical, LuNewspaper, LuShieldQuestion } from "react-icons/lu";
import type { SignalList, SignalRow } from "../api/models";
import { useTitle } from "../components/layout";
import { Card, Chip, Empty, ErrorState, LinkButton, Loading, MultiSelect, PageHeader, type Tone } from "../components/ui";
import { fmtDate, fmtDateTime, fmtPct, humanize } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, listParam, setQuery, useLocation } from "../lib/router";
import { useSession } from "../lib/session";

function kindOf(s: SignalRow): { label: string; tone: Tone; icon: ReactNode } {
  if (s.verification === "SYNTHETIC") return { label: "Synthetic demo signal (not real)", tone: "neutral", icon: <LuFlaskConical aria-hidden /> };
  if (s.verification === "VERIFIED_SOURCE" && s.signal_type === "OFFICIAL_NOTICE") return { label: "Official notice, source verified", tone: "green", icon: <LuBadgeCheck aria-hidden /> };
  if (s.verification === "VERIFIED_SOURCE") return { label: "Published reporting, source verified", tone: "blue", icon: <LuNewspaper aria-hidden /> };
  return { label: `${humanize(s.signal_type)}, not verified by AgniDrishti`, tone: "orange", icon: <LuShieldQuestion aria-hidden /> };
}

export function SignalsPage() {
  useTitle("Public Signals");
  const { params } = useLocation();
  const { can } = useSession();
  const query = { signal_type: listParam(params, "type"), verification: listParam(params, "verification"), match_status: listParam(params, "match") };
  const { data, error, loading, reload } = useApi<SignalList>("/api/signals", query);
  const cache = data?.sources?.cache as { status?: string; how?: string; generated_at?: string; items?: Array<{ status: string }> } | undefined;
  return (
    <div>
      <PageHeader title="Public signals"
        subtitle="Public notices and published reporting kept as context, in a separate layer from complaints."
        actions={can("signals.import") && <LinkButton to="/imports" size="sm">Import signals</LinkButton>} />
      {data && (
        <div className="mb-4 rounded-lg border-2 border-navy/30 bg-navy-soft px-4 py-3 text-sm text-navy-ink" role="note">
          <strong>{data.disclaimer}</strong>
          {data.sources.description ? <p className="mt-1 text-ink">{String(data.sources.description)}</p> : null}
          {data.sources.retrieval_note ? <p className="mt-1 text-xs text-muted">{String(data.sources.retrieval_note)}</p> : null}
          <p className="mt-1 text-xs text-muted">Local cache: {cache?.items ? `${cache.items.filter((i) => i.status === "CACHED").length} of ${cache.items.length} sources cached (${fmtDateTime(cache.generated_at)})` : `${cache?.status ?? "not cached"}. ${cache?.how ?? ""}`}</p>
        </div>
      )}
      <div className="mb-4 flex flex-wrap gap-2 rounded-lg border border-line bg-white p-3">
        <MultiSelect label="Type" className="w-full sm:w-56" value={query.signal_type} onChange={(v) => setQuery({ type: v })}
          options={[{ value: "OFFICIAL_NOTICE", label: "Official notice" }, { value: "NEWS_REPORT", label: "News / published report" }, { value: "SYNTHETIC_DEMO", label: "Synthetic demo" }]} />
        <MultiSelect label="Verification" className="w-full sm:w-60" value={query.verification} onChange={(v) => setQuery({ verification: v })}
          options={[{ value: "VERIFIED_SOURCE", label: "Source verified" }, { value: "UNVERIFIED", label: "Not verified" }, { value: "SYNTHETIC", label: "Synthetic" }]} />
        <MultiSelect label="Institution match" className="w-full sm:w-60" value={query.match_status} onChange={(v) => setQuery({ match: v })}
          options={[{ value: "MATCHED", label: "Matched" }, { value: "UNCERTAIN", label: "Uncertain match" }, { value: "NO_MATCH", label: "No institution / sector-wide" }]} />
      </div>
      {error && <ErrorState error={error} onRetry={reload} />}
      {!data && loading && <Loading />}
      {data && data.items.length === 0 && <Empty title="No public signals match">No verified signal is stored for this filter. Signals can be added through the import wizard with their source URL.</Empty>}
      <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        {data?.items.map((s) => {
          const k = kindOf(s);
          return (
            <li key={s.id}>
              <Card className="h-full">
                <p className="mb-2 flex flex-wrap items-center gap-2"><Chip tone={k.tone} icon={k.icon}>{k.label}</Chip>
                  <Chip tone="neutral">{s.scope === "SECTOR" ? "Sector-wide" : "Institution-specific"}</Chip></p>
                <h2 className="text-base font-semibold text-navy-ink">{s.title}</h2>
                <p className="mt-0.5 text-xs text-muted">{s.publisher ?? "—"}{s.published_date ? `, published ${fmtDate(s.published_date)}` : ""}{s.retrieved_at ? `, retrieved ${fmtDateTime(s.retrieved_at)}` : ""}</p>
                <p className="mt-2 text-sm text-ink">{s.summary}</p>
                <p className="mt-2 text-xs text-muted">
                  Institution: {s.institution_id ? <Link to={`/institutions/${s.institution_id}`}>{s.institution_name}</Link> : s.raw_institution_text ? `“${s.raw_institution_text}” (not linked)` : "none named"}
                  {", "}match {humanize(s.match_status).toLowerCase()}{s.match_confidence !== null ? ` (${fmtPct(s.match_confidence)})` : ""}
                </p>
                {s.notes && <p className="mt-1 text-xs text-muted">{s.notes}</p>}
                <p className="mt-2 text-sm">
                  {s.source_url ? <a href={s.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 font-semibold">Open source <LuExternalLink aria-hidden /></a>
                    : <span className="text-muted">No link: this is a synthetic layout example, not a real public signal.</span>}
                </p>
              </Card>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
