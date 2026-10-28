import { useState } from "react";
import { LuSplit } from "react-icons/lu";
import { api } from "../api/client";
import type { MasterDetail } from "../api/models";
import { useTitle } from "../components/layout";
import { BureauTag, Button, Card, Chip, ErrorState, Field, InlineError, KeyValues, Loading, Modal, PageHeader, StatusChip } from "../components/ui";
import { fmtDate, fmtDateTime, humanize, roleLabel } from "../lib/format";
import { useAction, useApi } from "../lib/hooks";
import { Link } from "../lib/router";
import { useRefData, useSession } from "../lib/session";
import { useToast } from "../lib/toast";

interface MasterRow {
  id: string;
  kind: string;
  institution_id: string;
  title: string;
  lead_bureau_code: string | null;
  status: string;
  overlap_alert_id: string | null;
  created_by: string | null;
  created_role: string | null;
  created_at: string;
  dissolved_by: string | null;
  dissolved_at: string | null;
  remarks: string | null;
}
interface Membership {
  id: number;
  case_id: string;
  added_by: string | null;
  added_at: string;
  removed_by: string | null;
  removed_at: string | null;
  remarks: string | null;
}
interface MemberBrief {
  id: string;
  status: string;
  bureau_code: string;
  category_code: string;
  received_date: string;
  master_case_id: string | null;
  institution_id: string;
  subject: string;
}

export function MasterCasePage({ id }: { id: string }) {
  useTitle("Master Case", id);
  const { data, error, loading, reload } = useApi<MasterDetail>(`/api/master-cases/${encodeURIComponent(id)}`);
  const ref = useRefData();
  const { me } = useSession();
  const [target, setTarget] = useState<string | null | undefined>(undefined);
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return loading ? <Loading /> : null;
  const m = data.master as unknown as MasterRow;
  const history = data.membership_history as unknown as Membership[];
  const cases = data.cases as unknown as MemberBrief[];
  const active = m.status === "ACTIVE";
  const isCA = me?.user.role === "COMPETENT_AUTHORITY";
  const sameBureau = cases.filter((c) => c.master_case_id === m.id).every((c) => c.bureau_code === me?.user.bureau_code);
  const canUnmerge = active && (isCA || (m.kind === "DUPLICATE_MERGE" && sameBureau && !!me?.user.bureau_code));
  return (
    <div>
      <PageHeader title={`${m.id}: ${m.title}`}
        subtitle="A Master Case groups records without changing them: each member keeps its own ID, timeline and audit trail."
        meta={<>
          <Chip tone={active ? "green" : "neutral"}>{humanize(m.status)}</Chip>
          <Chip tone="navy">{m.kind === "COORDINATION" ? "Coordinated matter" : "Duplicate group"}</Chip>
          {m.lead_bureau_code && <Chip tone="blue">Lead {m.lead_bureau_code}</Chip>}
        </>}
        actions={canUnmerge && <Button icon={<LuSplit aria-hidden />} onClick={() => setTarget(null)}>Dissolve Master Case</Button>} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Details">
          <KeyValues cols={1} items={[
            ["Institution", <Link to={`/institutions/${m.institution_id}`}>{m.institution_id}</Link>],
            ["Created", `${fmtDateTime(m.created_at)} by ${m.created_by ?? "—"} (${roleLabel(m.created_role)})`],
            ["From overlap alert", m.overlap_alert_id ? <Link to={`/overlaps/${m.overlap_alert_id}`}>{m.overlap_alert_id}</Link> : "—"],
            ["Lead Bureau/Cell", m.lead_bureau_code ? ref.bureauName(m.lead_bureau_code) : "Not set"],
            ["Remarks", m.remarks ?? "—"],
            ["Dissolved", m.dissolved_at ? `${fmtDateTime(m.dissolved_at)} by ${m.dissolved_by}` : "—"],
          ]} />
        </Card>
        <Card className="xl:col-span-7" title="Member cases">
          <table className="data-table">
            <thead><tr><th scope="col">Case</th><th scope="col">Bureau</th><th scope="col">Category</th><th scope="col">Status</th><th scope="col">Received</th><th scope="col" /></tr></thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/cases/${c.id}`} className="font-semibold">{c.id}</Link><span className="block text-xs text-muted">{c.subject}</span></td>
                  <td><BureauTag code={c.bureau_code} /></td>
                  <td>{ref.categoryLabel(c.category_code)}</td>
                  <td><StatusChip status={c.status} />{c.master_case_id !== m.id && <span className="block text-xs text-muted">no longer a member</span>}</td>
                  <td className="num">{fmtDate(c.received_date)}</td>
                  <td>{canUnmerge && c.master_case_id === m.id && <Button size="sm" onClick={() => setTarget(c.id)}>Remove</Button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card className="xl:col-span-12" title="Membership history" subtitle="Additions and removals are kept; nothing is deleted">
          <ol className="space-y-1.5 text-sm">
            {history.map((h) => (
              <li key={h.id}>
                <Link to={`/cases/${h.case_id}`}>{h.case_id}</Link> added {fmtDateTime(h.added_at)} by {h.added_by ?? "—"}
                {h.removed_at && <span className="text-orange-ink">; removed {fmtDateTime(h.removed_at)} by {h.removed_by}</span>}
                {h.remarks && <span className="text-muted"> ({h.remarks})</span>}
              </li>
            ))}
          </ol>
        </Card>
      </div>
      <UnmergeDialog masterId={m.id} caseId={target} onClose={() => setTarget(undefined)} onDone={() => {
        setTarget(undefined);
        reload();
      }} />
    </div>
  );
}

function UnmergeDialog({ masterId, caseId, onClose, onDone }: { masterId: string; caseId: string | null | undefined; onClose: () => void; onDone: () => void }) {
  const [remarks, setRemarks] = useState("");
  const { busy, error, run } = useAction();
  const toast = useToast();
  const { bump } = useSession();
  if (caseId === undefined) return null;
  return (
    <Modal open title={caseId ? `Remove ${caseId} from ${masterId}` : `Dissolve ${masterId}`} onClose={onClose}
      description="Memberships are closed, not deleted. A Master Case with fewer than two members is dissolved automatically."
      footer={<>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="danger" busy={busy} disabled={remarks.trim().length < 5} onClick={async () => {
          const out = await run(() => api.post(`/api/master-cases/${masterId}/unmerge`, { case_id: caseId, remarks }));
          if (out !== undefined) {
            toast.push("Unmerge recorded.");
            bump();
            setRemarks("");
            onDone();
          }
        }}>{caseId ? "Remove case" : "Dissolve"}</Button>
      </>}>
      <Field label="Remarks" required hint="Recorded in each member's timeline and in the audit trail.">
        {(id) => <textarea id={id} rows={3} className="field-input" value={remarks} onChange={(e) => setRemarks(e.target.value)} />}
      </Field>
      <div className="mt-3"><InlineError error={error} /></div>
    </Modal>
  );
}
