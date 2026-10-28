"""Phase 2: risk index + shrinkage, Hawkes forecast safeguards, trust graph, audit chain, workflow."""

from __future__ import annotations

import math
import random
from datetime import date

import numpy as np
import pytest

from app.alerts.service import sweep
from app.audit import chain
from app.core.errors import ApiError
from app.core.security import resolve_user
from app.graph.service import build as build_graph
from app.risk import hawkes
from app.risk import index as risk
from app.workflow import service as wf

TODAY = date(2026, 10, 27)


def test_risk_index_demo_institutions(ro_db):
    allr = risk.compute_all(ro_db, TODAY)["institutions"]
    assert all(0 <= r["score"] <= 100 for r in allr.values())
    a = allr["INS-0001"]
    assert a["band"] == "HIGH" and a["trend"] == "RISING" and a["delta_6m"] > 5
    assert a["components"]["cases_considered"] >= 15 and a["caveats"]
    rising = allr["INS-0005"]
    assert rising["trend"] == "RISING" and rising["forecast"]["trend"] == "RISING"


def test_shrinkage_tames_single_case_institutions(ro_db):
    cfg = {"half_life_days": 365, "outcome_factors": {"SUBSTANTIATED": 1.0, "OPEN": 0.6}, "intake_fallback": 600,
           "prior_strength_students": 500, "serious_min_severity": 4}
    insts = [{"id": f"X{i}", "intake_total": 600} for i in range(10)] + [{"id": "SMALL", "intake_total": 60}]
    loads = {f"X{i}": {"load": 5.0} for i in range(10)}
    loads["SMALL"] = {"load": 5.0}  # one serious substantiated case at a tiny institution
    shrunk = risk._scores(insts, loads, cfg)["SMALL"]["score"]
    raw_cfg = dict(cfg, prior_strength_students=0)
    unshrunk = risk._scores(insts, loads, raw_cfg)["SMALL"]["score"]
    assert unshrunk > 85 and shrunk < unshrunk - 15


def test_missing_intake_is_flagged(db):
    with db.tx():
        db.run("UPDATE institutions SET intake_total = NULL, intake_source = NULL, updated_at = '2099-01-01T00:00:00Z' "
               "WHERE id = 'INS-0020'")
    r = risk.for_institution(db, "INS-0020", TODAY)
    assert r["components"]["intake_known"] is False
    assert any("fallback intake" in c for c in r["caveats"])
    assert r["confidence"] in ("MEDIUM", "LOW")


def _simulate(mu, alpha, beta, T, seed):
    rng = random.Random(seed)
    events, t = [], 0.0
    while True:
        lam_bar = mu + alpha * beta * sum(math.exp(-beta * (t - s)) for s in events[-50:]) + alpha * beta
        t += rng.expovariate(lam_bar)
        if t > T:
            return events
        lam_t = mu + alpha * beta * sum(math.exp(-beta * (t - s)) for s in events[-50:])
        if rng.random() <= lam_t / lam_bar:
            events.append(t)


def test_hawkes_fit_and_fallbacks():
    T = 2800.0
    ev = _simulate(mu=0.01, alpha=0.5, beta=1 / 30.0, T=T, seed=7)
    assert len(ev) >= 20
    fit = hawkes.fit(ev, T)
    assert fit["converged"] and 0.2 < fit["alpha"] < 0.8
    pooled = {"alpha": 0.3, "beta": 1 / 40.0, "mu_mean": 0.003}
    fc = hawkes.forecast(ev, T, pooled)
    assert fc["status"] == "FITTED" and 0 <= fc["interval_80"][0] <= fc["probability"] <= 1
    sparse = hawkes.forecast([100.0, 900.0, 2500.0], T, pooled)
    assert sparse["status"] == "POOLED_FALLBACK" and sparse["confidence"] == "LOW" and sparse["notes"]
    empty = hawkes.forecast([], T, pooled)
    assert empty["status"] == "BASELINE_NO_EVENTS" and 0 < empty["probability"] < 0.5
    burst = hawkes.forecast([1000.0] * 3 + [1000.5] * 6, T, pooled)  # degenerate: identical timestamps
    assert burst["status"] in ("FITTED", "POOLED_FALLBACK") and np.isfinite(burst["probability"])


def test_trust_graph_uses_stored_relationships(ro_db):
    ca = resolve_user(ro_db, "competent.authority")
    g = build_graph(ro_db, ca, TODAY)
    trusts = [n for n in g["nodes"] if n["kind"] == "trust"]
    assert len(trusts) == 8 and all(e["relation"] == "OPERATED_BY" for e in g["edges"])
    navankur = next(x for x in g["groups"] if x["trust_id"] == "TRS-02")
    assert navankur["members"] == 5 and navankur["flagged_members"] >= 2 and navankur["patterns"]
    edge_insts = {e["target"] for e in g["edges"]}
    stored = {f"I:{r['id']}" for r in ro_db.all("SELECT id FROM institutions WHERE trust_id IS NOT NULL")}
    assert edge_insts == stored
    keys = {n["key"] for n in g["nodes"]}
    trust_of = {f"I:{r['id']}": f"T:{r['trust_id']}" for r in ro_db.all("SELECT id, trust_id FROM institutions WHERE trust_id IS NOT NULL")}
    assert all(e["source"] in keys and e["target"] in keys and trust_of[e["target"]] == e["source"] for e in g["edges"])
    assert all(e["provenance"] == "SYNTHETIC" for e in g["edges"])
    ro = resolve_user(ro_db, "ro.central")
    g2 = build_graph(ro_db, ro, TODAY)
    assert all(n["region"] == "CENTRAL" for n in g2["nodes"] if n["kind"] == "institution")


def test_audit_chain_detects_tampering(db):
    assert chain.verify(db)["ok"]
    pgrc = resolve_user(db, "pgrc.officer")
    wf.add_action(db, pgrc, "PGRC-5530", "REMARK", remarks="Called institution registrar")
    res = chain.verify(db)
    assert res["ok"] and res["checked"] >= 3
    seq = db.val("SELECT seq FROM audit_events WHERE action = 'CASE_ACTION_REMARK' ORDER BY seq DESC LIMIT 1")
    with db.tx():
        db.run("UPDATE audit_events SET remarks = 'edited' WHERE seq = ?", (seq,))
    bad = chain.verify(db)
    assert not bad["ok"] and bad["first_bad_seq"] == seq and "payload" in bad["reason"]
    with db.tx():
        db.run("UPDATE audit_events SET remarks = 'Called institution registrar' WHERE seq = ?", (seq,))
    assert chain.verify(db)["ok"]
    with db.tx():
        db.run("DELETE FROM audit_events WHERE seq = (SELECT MIN(seq) + 1 FROM audit_events)")
    assert not chain.verify(db)["ok"]


def test_workflow_transitions_permissions_and_alerts(db):
    pgrc = resolve_user(db, "pgrc.officer")
    rb = resolve_user(db, "rb.officer")
    ro = resolve_user(db, "ro.central")
    sm = resolve_user(db, "senior.mgmt")
    with pytest.raises(ApiError) as e:
        wf.change_status(db, rb, "PGRC-5530", "PENDING", "rb cannot")
    assert e.value.status == 403
    with pytest.raises(ApiError):
        wf.add_action(db, sm, "PGRC-5530", "REMARK", remarks="read-only role")
    wf.add_action(db, ro, "PGRC-5530", "REMARK", remarks="Regional office spoke to institution")
    with pytest.raises(ApiError):
        wf.change_status(db, ro, "PGRC-5530", "PENDING", "ro cannot change status")
    with pytest.raises(ApiError) as e2:
        wf.assign(db, pgrc, "PGRC-5530", "OFF-RB-01")
    assert e2.value.status == 422
    wf.assign(db, pgrc, "PGRC-5530", "OFF-PGRC-04", "Reassigned for workload")
    t = wf.transfer(db, pgrc, "PGRC-4466", "RB", "Certificates withheld as leverage for regulatory fee: RB matter")
    assert t["status"] == "TRANSFERRED"
    assert db.one("SELECT 1 FROM alerts WHERE case_id='PGRC-4466' AND target_bureau='RB'")
    wf.assign(db, rb, "PGRC-4466", "OFF-RB-03", "Accepting transfer")
    assert db.one("SELECT status FROM complaints WHERE id='PGRC-4466'")["status"] == "PENDING"
    wf.escalate(db, pgrc, "PGRC-5530", "Institution not cooperating; needs CA attention")
    ca = resolve_user(db, "competent.authority")
    wf.deescalate(db, ca, "PGRC-5530", "Directions issued; continue inquiry")
    sweep(db, TODAY)
    assert db.val("SELECT COUNT(*) FROM alerts WHERE case_id='PGRC-5530' AND state IN ('NEW','ACKNOWLEDGED')") >= 1
    wf.dispose(db, pgrc, "PGRC-5530", "SUBSTANTIATED", "Refund ordered within 15 days; compliance report sought")
    assert db.val("SELECT COUNT(*) FROM alerts WHERE case_id='PGRC-5530' AND alert_type LIKE 'SLA%' AND state IN ('NEW','ACKNOWLEDGED')") == 0
    with pytest.raises(ApiError):
        wf.dispose(db, pgrc, "PGRC-5530", "SUBSTANTIATED", "again")
    types = [r["action_type"] for r in db.all("SELECT action_type FROM case_actions WHERE case_id='PGRC-5530' ORDER BY id")]
    for kind in ("REMARK", "ASSIGNED", "ESCALATED", "DEESCALATED", "DISPOSED"):
        assert kind in types
    assert chain.verify(db)["ok"]
    with pytest.raises(ApiError):
        wf.add_document(db, pgrc, "PGRC-6001", "EVIDENCE", "Script", file_name="x.exe", content=b"MZ")
    out = wf.add_document(db, ca, "PGRC-6001", "EVIDENCE", "Fee receipt scan", file_name="receipt.pdf", content=b"%PDF-1.4 test")
    assert out["stored"] and len(out["sha256"]) == 64


def test_alert_sweep_is_idempotent(db):
    first = sweep(db, TODAY)
    second = sweep(db, TODAY)
    assert sum(v for k, v in second.items() if k != "auto_resolved") == 0
    assert isinstance(first, dict)
