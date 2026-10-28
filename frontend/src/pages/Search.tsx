import type { FormEvent } from "react";
import { useEffect, useState } from "react";
import { LuBuilding2, LuSearch } from "react-icons/lu";
import type { CasePage, SearchOut } from "../api/models";
import { CaseTable, UrlTextInput } from "../components/cases";
import { FilterBar, urlFilters } from "../components/filters";
import { useTitle } from "../components/layout";
import { Button, Card, Chip, Empty, ErrorState, Loading, PageHeader, Pagination, SelectInput } from "../components/ui";
import { fmtNum, fmtPct } from "../lib/format";
import { useApi } from "../lib/hooks";
import { Link, setQuery, useLocation } from "../lib/router";

const SORTS = [
  { value: "received_desc", label: "Newest received" },
  { value: "received_asc", label: "Oldest received" },
  { value: "priority_desc", label: "Highest priority" },
  { value: "due_asc", label: "Due soonest" },
  { value: "status", label: "Status" },
  { value: "id", label: "Case ID" },
];

interface InstitutionHit {
  id: string;
  name: string;
  permanent_id: string | null;
  state: string;
  confidence: number;
  band: string;
  match: string;
  uncertain: boolean;
}

export function SearchPage() {
  useTitle("Global Search");
  const { params } = useLocation();
  const q = params.get("q") ?? "";
  const page = Number(params.get("page") ?? "1") || 1;
  const pageSize = Number(params.get("page_size") ?? "25") || 25;
  const query = {
    ...urlFilters(params, ["dates", "bureau", "region", "state", "category", "status", "priority"]),
    q: q || undefined,
    institution: params.get("institution") || undefined,
    institution_id: params.get("institution_id") || undefined,
    permanent_id: params.get("permanent_id") || undefined,
    case_id: params.get("case_id") || undefined,
    master_case_id: params.get("master_case_id") || undefined,
    demo_tag: params.get("demo_tag") || undefined,
    overdue: params.get("overdue") === "true" ? true : undefined,
    open_only: params.get("open_only") === "true" ? true : undefined,
    has_overlap: params.get("has_overlap") === "true" ? true : undefined,
    sort: params.get("sort") || "received_desc",
    page,
    page_size: pageSize,
  };
  const cases = useApi<CasePage>("/api/cases", query);
  const global = useApi<SearchOut>(q.length >= 2 ? "/api/search" : null, { q });

  return (
    <div>
      <PageHeader title="Search cases and institutions"
        subtitle="Search by institution name or alias (fuzzy, via entity resolution), AICTE Permanent ID, case or reference number, and combine any filters." />
      <SearchBox initial={q} />
      {q.length >= 2 && <InstitutionHits data={global.data} loading={global.loading} q={q} />}
      <FilterBar show={["dates", "bureau", "region", "state", "category", "status", "priority"]}
        resetKeys={["q", "institution", "institution_id", "permanent_id", "case_id", "overdue", "open_only", "has_overlap", "master_case_id", "demo_tag"]}>
        <UrlTextInput param="institution" label="Institution name or alias" placeholder="e.g. SIET Bhopal" className="w-full sm:w-52" />
        <UrlTextInput param="permanent_id" label="AICTE Permanent ID" placeholder="e.g. SYN-1-41730052" className="w-full sm:w-44" />
        <UrlTextInput param="case_id" label="Case ID" placeholder="e.g. PGRC-5530" className="w-full sm:w-36" />
        <fieldset className="flex flex-wrap items-center gap-3 pb-2 text-sm">
          <legend className="sr-only">Case conditions</legend>
          {([["open_only", "Open only"], ["overdue", "Overdue"], ["has_overlap", "Has overlap alert"]] as const).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5">
              <input type="checkbox" checked={params.get(k) === "true"} onChange={(e) => setQuery({ [k]: e.target.checked ? "true" : null, page: null })} />
              {label}
            </label>
          ))}
        </fieldset>
      </FilterBar>
      {(params.get("institution_id") || params.get("master_case_id") || params.get("demo_tag")) && (
        <p className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          {params.get("institution_id") && <Chip tone="blue">Institution {params.get("institution_id")}</Chip>}
          {params.get("master_case_id") && <Chip tone="blue">Master Case {params.get("master_case_id")}</Chip>}
          {params.get("demo_tag") && <Chip tone="navy">Demo: {params.get("demo_tag")}</Chip>}
          <Button size="sm" variant="ghost" onClick={() => setQuery({ institution_id: null, master_case_id: null, demo_tag: null, page: null })}>Remove</Button>
        </p>
      )}
      <Card title={cases.data ? `${fmtNum(cases.data.total)} case${cases.data.total === 1 ? "" : "s"} found` : "Cases"}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="sort" className="text-xs text-muted">Sort</label>
            <SelectInput id="sort" value={query.sort} onChange={(v) => setQuery({ sort: v === "received_desc" ? null : v, page: null })} options={SORTS} className="w-44" />
            <label htmlFor="page-size" className="text-xs text-muted">Rows</label>
            <SelectInput id="page-size" value={String(pageSize)} onChange={(v) => setQuery({ page_size: v === "25" ? null : v, page: null })}
              options={["25", "50", "100"].map((x) => ({ value: x, label: x }))} className="w-20" />
          </div>
        }>
        {cases.error && <ErrorState error={cases.error} onRetry={cases.reload} />}
        {!cases.data && cases.loading && <Loading />}
        {cases.data && cases.data.total === 0 && (
          <Empty title="No cases match these filters">Clear one or more filters, or search by a different spelling — institution names are matched fuzzily.</Empty>
        )}
        {cases.data && cases.data.total > 0 && (
          <div className={cases.loading ? "opacity-60" : ""}>
            <CaseTable rows={cases.data.items} />
            <Pagination page={page} pageSize={pageSize} total={cases.data.total} onPage={(p) => setQuery({ page: p === 1 ? null : p })} />
          </div>
        )}
      </Card>
    </div>
  );
}

function SearchBox({ initial }: { initial: string }) {
  const [value, setValue] = useState(initial);
  useEffect(() => setValue(initial), [initial]);
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setQuery({ q: value.trim() || null, page: null });
  };
  return (
    <form role="search" onSubmit={submit} className="mb-3 flex gap-2">
      <label htmlFor="global-q" className="sr-only">Search text</label>
      <div className="relative flex-1">
        <LuSearch aria-hidden className="absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
        <input id="global-q" value={value} onChange={(e) => setValue(e.target.value)}
          placeholder="Institution name or alias, Permanent ID, case ID, source or CPGRAMS reference, subject words"
          className="field-input py-2.5 pl-9 text-base" />
      </div>
      <Button type="submit" variant="primary" icon={<LuSearch aria-hidden />}>Search</Button>
    </form>
  );
}

function InstitutionHits({ data, loading, q }: { data: SearchOut | undefined; loading: boolean; q: string }) {
  if (!data) return loading ? <Loading label="Matching institutions…" /> : null;
  const hits = data.institutions as unknown as InstitutionHit[];
  return (
    <Card className="mb-4" title="Institution matches" subtitle={data.note}>
      {hits.length === 0 ? <p className="text-sm text-muted">No institution in the Institution Master matches “{q}”.</p> : (
        <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
          {hits.map((h) => (
            <li key={h.id} className="flex items-start gap-3 rounded-md border border-line p-3">
              <LuBuilding2 aria-hidden className="mt-0.5 text-lg text-navy" />
              <div className="min-w-0 flex-1">
                <Link to={`/institutions/${h.id}`} className="font-semibold">{h.name}</Link>
                <p className="text-xs text-muted">{h.permanent_id ?? "No Permanent ID"}, {h.state}</p>
                <p className="mt-1 flex flex-wrap items-center gap-1.5">
                  {h.uncertain ? <Chip tone="orange" title="Below the auto-link threshold: verify before relying on it">Uncertain match {fmtPct(h.confidence)}</Chip>
                    : <Chip tone="green">{h.match === "TEXT" ? "Name/alias match" : "Match"} {fmtPct(h.confidence)}</Chip>}
                  <button type="button" className="text-xs font-semibold text-blue-ink hover:underline"
                    onClick={() => setQuery({ institution_id: h.id, q: null, page: null })}>Show this institution’s cases</button>
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
      {(data.cases as unknown[]).length > 0 && <p className="mt-2 text-xs text-muted">Case and reference matches are listed in the results below.</p>}
    </Card>
  );
}
