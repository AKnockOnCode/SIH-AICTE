"""Conflict-of-Action detector: DUPLICATE, RELATED and CONFLICT tiers.

Runs when a case is created, when a regulatory action is added to a case, after an
institution match is confirmed, and as a batch scan. Only cases linked to the *same
canonical institution* are compared, and a pair is flagged only if a named rule fires —
sharing an institution alone is never enough.

DUPLICATE (likely the same grievance filed twice)
  D1 same external reference (e.g. CPGRAMS registration number)
  D2 same category, TF-IDF text similarity >= duplicate_text_min, received within duplicate_window_days
  D3 same issue family, similarity >= duplicate_strong_text, within duplicate_strong_window_days
CONFLICT (coordination-sensitive actions across Bureaus/Cells)
  C1 favourable regulatory action (renewal/approval/extension/intake increase/NOC) by one Bureau
     within action_window_days while a case of severity >= open_min_severity is OPEN at another
  C2 favourable regulatory action while another Bureau's case of severity >=
     substantiated_min_severity was SUBSTANTIATED (fully/partly) within substantiated_lookback_days
  C3 adverse regulatory action (show-cause/closure/withdrawal/penalty) while another Bureau has an
     open case that may require the institution's compliance (refunds, documents)
  C4 parallel fact-finding: both cases open at different Bureaus, same family, inspections ordered
RELATED (link for context)
  R1 same issue family, both open, within related_window_days (same Bureau/Cell)
  R2 text similarity >= related_text_min within related_window_days (one case open)
  R3 same issue family, both open, at different Bureaus/Cells
Precedence: CONFLICT > DUPLICATE > RELATED. Alerts are de-duplicated and merged per
institution and tier; resolved/dismissed pairs are not re-raised unless a new pair appears.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..audit import chain
from ..core.clock import now_iso
from ..core.clock import today as clock_today
from ..core.constants import COORDINATION_HEADLINE
from ..core.security import SYSTEM_USER, User
from ..core.util import clamp, dumps, loads, next_id
from ..scoring.rules import category_rules, get_settings_block
from . import lead as lead_mod
from .text import get_index

SUBSTANTIATED = ("SUBSTANTIATED", "PARTIALLY_SUBSTANTIATED")


def _reg_actions(db, case_ids: list[str], kinds: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not case_ids or not kinds:
        return {}
    cm = ",".join("?" for _ in case_ids)
    km = ",".join("?" for _ in kinds)
    out: dict[str, list[dict[str, Any]]] = {}
    for a in db.all(f"SELECT id, case_id, action_type, action_at, bureau_code, actor_label FROM case_actions "
                    f"WHERE case_id IN ({cm}) AND action_type IN ({km}) ORDER BY action_at", (*case_ids, *kinds)):
        out.setdefault(a["case_id"], []).append(a)
    return out


def _active(actions: list[dict[str, Any]], today: date, window: int) -> list[dict[str, Any]]:
    cutoff = (today - timedelta(days=window)).isoformat()
    return [a for a in actions if a["action_at"][:10] >= cutoff]


def _inspections(db, case_ids: list[str], today: date) -> set[str]:
    if not case_ids:
        return set()
    cm = ",".join("?" for _ in case_ids)
    cutoff = (today - timedelta(days=90)).isoformat()
    return {r["case_id"] for r in db.all(
        f"SELECT DISTINCT case_id FROM case_actions WHERE case_id IN ({cm}) AND action_type = 'INSPECTION_ORDERED' "
        f"AND action_at >= ?", (*case_ids, cutoff))}


def _case_ref(case: dict[str, Any], label: str) -> str:
    """'fee fraud case PGRC-5530', or 'the new fee fraud complaint' for the unsaved intake preview."""
    return f"the new {label} complaint" if case["id"] == "NEW" else f"{label} case {case['id']}"


def evaluate_pairs(db, trigger: dict[str, Any], others: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Evaluate the trigger case against other cases of the same institution."""
    cfg = get_settings_block(db, "conflict")
    rules = category_rules(db)
    ids = [trigger["id"]] + [o["id"] for o in others]
    fav = _reg_actions(db, ids, cfg["favourable_actions"])
    adv = _reg_actions(db, ids, cfg["adverse_actions"])
    insp = _inspections(db, ids, today)
    sims = get_index(db).similarities(trigger, others)
    t_rule = rules[trigger["category_code"]]
    results = []
    for o in others:
        o_rule = rules[o["category_code"]]
        days = abs((date.fromisoformat(trigger["received_date"]) - date.fromisoformat(o["received_date"])).days)
        sim = sims.get(o["id"], 0.0)
        same_cat = trigger["category_code"] == o["category_code"]
        same_fam = t_rule["family"] == o_rule["family"]
        cross = trigger["bureau_code"] != o["bureau_code"]
        t_open, o_open = trigger["status"] != "DISPOSED", o["status"] != "DISPOSED"
        ext = bool(trigger.get("external_ref")) and trigger.get("external_ref") == o.get("external_ref")
        conflict_rules: list[dict[str, str]] = []
        dup_rules: list[dict[str, str]] = []
        rel_rules: list[dict[str, str]] = []
        fav_action = None
        # ---- CONFLICT
        if cross:
            for a_case, b_case in ((trigger, o), (o, trigger)):
                a_fav = _active(fav.get(a_case["id"], []), today, int(cfg["action_window_days"]))
                a_adv = _active(adv.get(a_case["id"], []), today, int(cfg["action_window_days"]))
                b_rule = rules[b_case["category_code"]]
                b_sev = int(b_rule["severity_level"])
                b_open = b_case["status"] != "DISPOSED"
                if a_fav and b_rule["family"] != "REGULATORY_PROCESS":
                    act = a_fav[-1]
                    fav_action = {"case_id": a_case["id"], "action_type": act["action_type"], "action_at": act["action_at"],
                                  "bureau_code": act["bureau_code"] or a_case["bureau_code"]}
                    if b_open and b_sev >= int(cfg["open_min_severity"]):
                        conflict_rules.append({"code": "C1", "text": f"{act['action_type'].replace('_', ' ').title()} by "
                                               f"{fav_action['bureau_code']} on {a_case['id']} while {_case_ref(b_case, b_rule['label'].lower())} "
                                               f"(severity {b_sev}/5) is open at {b_case['bureau_code']}"})
                    elif (not b_open and b_case.get("outcome") in SUBSTANTIATED and b_sev >= int(cfg["substantiated_min_severity"])
                          and b_case.get("disposed_date")
                          and (today - date.fromisoformat(b_case["disposed_date"])).days <= int(cfg["substantiated_lookback_days"])):
                        conflict_rules.append({"code": "C2", "text": f"{act['action_type'].replace('_', ' ').title()} on "
                                               f"{a_case['id']} although {b_rule['label'].lower()} case {b_case['id']} was "
                                               f"{b_case['outcome'].replace('_', ' ').lower()} on {b_case['disposed_date']}"})
                if a_adv and b_open and b_sev >= 2 and b_rule["family"] != "REGULATORY_PROCESS":
                    act = a_adv[-1]
                    conflict_rules.append({"code": "C3", "text": f"{act['action_type'].replace('_', ' ').title()} by "
                                           f"{act['bureau_code'] or a_case['bureau_code']} on {a_case['id']} while "
                                           f"{'the new complaint' if b_case['id'] == 'NEW' else b_case['id']} awaits the "
                                           f"institution's response at {b_case['bureau_code']}"})
            if t_open and o_open and same_fam and trigger["id"] in insp and o["id"] in insp:
                conflict_rules.append({"code": "C4", "text": "Parallel fact-finding: inspections ordered by two Bureaus/Cells "
                                       "on the same issue family"})
        # ---- DUPLICATE
        if ext:
            dup_rules.append({"code": "D1", "text": f"Same external reference {trigger['external_ref']}"})
        if same_cat and sim >= float(cfg["duplicate_text_min"]) and days <= int(cfg["duplicate_window_days"]):
            dup_rules.append({"code": "D2", "text": f"Same category, text similarity {sim:.0%}, received {days} day(s) apart"})
        if same_fam and sim >= float(cfg["duplicate_strong_text"]) and days <= int(cfg["duplicate_strong_window_days"]):
            dup_rules.append({"code": "D3", "text": f"Same issue family, very similar text ({sim:.0%}), {days} day(s) apart"})
        # ---- RELATED
        if t_open and o_open and same_fam and days <= int(cfg["related_window_days"]):
            if cross:
                rel_rules.append({"code": "R3", "text": f"Same issue family ({t_rule['family'].lower()}) open at two "
                                  f"Bureaus/Cells ({trigger['bureau_code']} and {o['bureau_code']})"})
            else:
                rel_rules.append({"code": "R1", "text": f"Same issue family ({t_rule['family'].lower()}), both open"})
        if sim >= float(cfg["related_text_min"]) and days <= int(cfg["related_window_days"]) and (t_open or o_open):
            rel_rules.append({"code": "R2", "text": f"Text similarity {sim:.0%} within {days} day(s)"})

        tier = None
        if conflict_rules:
            tier = "CONFLICT"
            sev = max(int(t_rule["severity_level"]), int(o_rule["severity_level"]))
            score = clamp(0.55 + 0.07 * sev + 0.05 * len(conflict_rules), 0, 0.99)
            fired = conflict_rules
        elif dup_rules:
            tier = "DUPLICATE"
            win = int(cfg["duplicate_strong_window_days"])
            score = clamp(0.45 * sim + 0.25 * max(0.0, 1 - days / win) + 0.15 * same_cat + 0.15 * ext, 0, 0.99)
            fired = dup_rules
        elif rel_rules:
            tier = "RELATED"
            score = clamp(0.35 + 0.35 * sim + 0.15 * same_fam + 0.15 * cross, 0, 0.95)
            fired = rel_rules
        if tier is None:
            continue
        results.append({
            "a": trigger["id"], "b": o["id"], "tier": tier, "score": round(score, 3), "rules": fired,
            "text_similarity": round(sim, 3), "days_apart": days, "same_category": same_cat, "same_family": same_fam,
            "external_ref_match": ext, "cross_bureau": cross, "favourable_action": fav_action,
        })
    return results


def _headline(tier: str, cross: bool) -> str:
    if tier == "CONFLICT" or (tier == "DUPLICATE" and cross):
        return COORDINATION_HEADLINE
    if tier == "DUPLICATE":
        return "Likely Duplicate Complaint – Review for Master Case"
    return "Related Cases Across Bureaus – Link for Context" if cross else "Related Cases – Link for Context"


def _next_step(tier: str, rules_fired: list[str], lead: str | None, members: list[dict[str, Any]]) -> str:
    lead_txt = lead or "the recommended Bureau/Cell"
    if tier == "CONFLICT":
        if "C1" in rules_fired or "C2" in rules_fired:
            return (f"Hold the favourable regulatory decision pending {lead_txt}'s findings on the open/serious "
                    f"grievance(s); share files between Bureaus/Cells and record a joint decision with the Competent Authority.")
        if "C3" in rules_fired:
            return "Coordinate before the adverse action so pending refunds/documents for complainants are protected."
        return f"Agree a single fact-finding under {lead_txt}; avoid parallel inspections."
    if tier == "DUPLICATE":
        return f"Verify and merge into a Master Case led by {lead_txt}; reply to the complainant once."
    return "Link the cases for context and inform the other Bureau/Cell; no merge needed."


def _members(db, alert_id: str) -> list[str]:
    return [r["case_id"] for r in db.all("SELECT case_id FROM overlap_alert_cases WHERE alert_id = ? ORDER BY case_id", (alert_id,))]


def _persist(db, inst: dict[str, Any], tier: str, trigger: dict[str, Any], pairs: list[dict[str, Any]],
             trigger_type: str, trigger_action: dict[str, Any] | None, actor: User, today: date) -> tuple[str | None, bool]:
    rules = category_rules(db)
    pair_keys = sorted({"|".join(sorted((p["a"], p["b"]))) for p in pairs})
    member_ids = sorted({p["a"] for p in pairs} | {p["b"] for p in pairs})
    # Merge into an open alert of the same tier that shares a member.
    open_alerts = db.all("SELECT * FROM overlap_alerts WHERE institution_id = ? AND tier = ? AND status IN ('OPEN','UNDER_REVIEW') "
                         "ORDER BY created_at", (inst["id"], tier))
    family = rules[trigger["category_code"]]["family"]
    target = None
    for al in open_alerts:
        # RELATED clusters are kept per issue family so they stay small and meaningful.
        if tier == "RELATED" and loads(al["signals_json"], {}).get("family") != family:
            continue
        if set(_members(db, al["id"])) & set(member_ids):
            target = al
            break
    if target is None:
        closed_keys: set[str] = set()
        for al in db.all("SELECT pair_keys_json FROM overlap_alerts WHERE institution_id = ? AND tier = ? AND "
                         "status IN ('RESOLVED','DISMISSED')", (inst["id"], tier)):
            closed_keys |= set(loads(al["pair_keys_json"], []))
        if set(pair_keys) <= closed_keys:
            return None, False  # already decided by an officer; do not re-raise
    cases = {c["id"]: c for c in db.all(
        f"SELECT * FROM complaints WHERE id IN ({','.join('?' for _ in member_ids)})", member_ids)}
    if target is not None:
        old_members = set(_members(db, target["id"]))
        all_ids = sorted(old_members | set(member_ids))
        cases.update({c["id"]: c for c in db.all(
            f"SELECT * FROM complaints WHERE id IN ({','.join('?' for _ in all_ids)})", all_ids)})
        old_signals = loads(target["signals_json"], {})
        known = {"|".join(sorted((p["a"], p["b"]))) for p in old_signals.get("pairs", [])}
        pairs = old_signals.get("pairs", []) + [p for p in pairs if "|".join(sorted((p["a"], p["b"]))) not in known]
        pair_keys = sorted(set(loads(target["pair_keys_json"], [])) | set(pair_keys))
        member_ids = all_ids
    cfg_lead = get_settings_block(db, "lead")
    cfg_conf = get_settings_block(db, "conflict")
    reg = _reg_actions(db, member_ids, cfg_conf["favourable_actions"] + cfg_conf["adverse_actions"])
    reg = {k: _active(v, today, int(cfg_conf["action_window_days"])) for k, v in reg.items()}
    members = [cases[m] for m in member_ids]
    rec = lead_mod.recommend(db, members, rules, cfg_lead, reg)
    cross = len({c["bureau_code"] for c in members}) > 1
    fired = sorted({r["code"] for p in pairs for r in p["rules"]})
    headline = _headline(tier, cross)
    score = max(p["score"] for p in pairs)
    explanation = (f"{len(members)} case(s) of {inst['name']} ({inst['id']}) handled by "
                   f"{', '.join(sorted({c['bureau_code'] for c in members}))}: " +
                   "; ".join(r["text"] for p in pairs for r in p["rules"]))
    signals = {
        "institution": {"id": inst["id"], "name": inst["name"], "permanent_id": inst["permanent_id"],
                        "match": [{"case_id": c["id"], "raw_name": c["institution_name_raw"], "match_status": c["match_status"],
                                   "confidence": c["match_confidence"]} for c in members]},
        "pairs": pairs,
        "trigger": {"type": trigger_type, "case_id": trigger["id"], "action": trigger_action},
        "family": family if target is None else loads(target["signals_json"], {}).get("family", family),
        "explanation": explanation,
    }
    now = now_iso()
    bureaus = sorted({c["bureau_code"] for c in members})
    if target is not None:
        db.update("overlap_alerts", "id", target["id"], {
            "headline": headline, "score": max(score, target["score"]), "cross_bureau": int(cross),
            "bureaus_json": dumps(bureaus), "rules_json": dumps(fired), "signals_json": dumps(signals),
            "recommended_lead": rec["recommended"], "recommendation_json": dumps(rec),
            "next_step": _next_step(tier, fired, rec["recommended"], members), "pair_keys_json": dumps(pair_keys),
            "updated_at": now,
        })
        for m in member_ids:
            db.run("INSERT OR IGNORE INTO overlap_alert_cases(alert_id, case_id, role) VALUES (?,?,?)",
                   (target["id"], m, "TRIGGER" if m == trigger["id"] else "MEMBER"))
        if set(member_ids) - old_members:
            chain.record(db, actor, "OVERLAP_UPDATED", "overlap_alert", target["id"],
                         after={"added_cases": sorted(set(member_ids) - old_members), "tier": tier})
        return target["id"], False
    alert_id = next_id(db, "overlap", "OVL-", 4)
    db.insert("overlap_alerts", {
        "id": alert_id, "institution_id": inst["id"], "tier": tier, "headline": headline, "score": score,
        "status": "OPEN", "trigger_type": trigger_type, "trigger_case_id": trigger["id"],
        "trigger_action_id": (trigger_action or {}).get("id"), "cross_bureau": int(cross), "bureaus_json": dumps(bureaus),
        "rules_json": dumps(fired), "signals_json": dumps(signals), "recommended_lead": rec["recommended"],
        "recommendation_json": dumps(rec), "next_step": _next_step(tier, fired, rec["recommended"], members),
        "lead_decision": None, "decided_lead": None, "decision_remarks": None, "decided_by": None, "decided_role": None,
        "decided_at": None, "status_remarks": None, "status_by": None, "status_at": None,
        "pair_keys_json": dumps(pair_keys), "created_at": now, "updated_at": now,
    })
    for m in member_ids:
        db.insert("overlap_alert_cases", {"alert_id": alert_id, "case_id": m,
                                          "role": "TRIGGER" if m == trigger["id"] else "MEMBER"})
    from ..alerts.notify import raise_alert

    sev = "CRITICAL" if tier == "CONFLICT" else "WARNING" if (tier == "DUPLICATE" or cross) else "INFO"
    for b in bureaus or [None]:
        raise_alert(db, alert_type="OVERLAP", severity=sev, title=f"{headline} — {inst['name']}",
                    message=f"{tier.title()} tier ({', '.join(fired)}): {', '.join(member_ids)}. {explanation[:300]}",
                    dedupe_key=f"OVERLAP:{alert_id}:{b}", institution_id=inst["id"], case_id=trigger["id"],
                    overlap_alert_id=alert_id, target_bureau=b, target_region=inst["region_code"])
    chain.record(db, actor, "OVERLAP_DETECTED", "overlap_alert", alert_id,
                 after={"tier": tier, "cases": member_ids, "rules": fired, "score": score,
                        "trigger": {"type": trigger_type, "case_id": trigger["id"]},
                        "recommended_lead": rec["recommended"]})
    return alert_id, True


def detect_for_case(db, case_id: str, *, trigger_type: str = "CASE_CREATED", trigger_action: dict[str, Any] | None = None,
                    actor: User | None = None, today: date | None = None) -> list[dict[str, Any]]:
    """Run the detector with `case_id` as trigger and persist alerts. Must be inside a transaction."""
    actor = actor or SYSTEM_USER
    today = today or clock_today()
    trigger = db.one("SELECT * FROM complaints WHERE id = ?", (case_id,))
    if trigger is None or trigger["institution_id"] is None:
        return []
    inst = db.one("SELECT * FROM institutions WHERE id = ?", (trigger["institution_id"],))
    cfg = get_settings_block(db, "conflict")
    horizon = (today - timedelta(days=max(int(cfg["related_window_days"]), int(cfg["substantiated_lookback_days"]),
                                          int(cfg["duplicate_strong_window_days"])))).isoformat()
    others = db.all("SELECT * FROM complaints WHERE institution_id = ? AND id != ? AND "
                    "(status != 'DISPOSED' OR received_date >= ? OR disposed_date >= ?)",
                    (trigger["institution_id"], case_id, horizon, horizon))
    pairs = evaluate_pairs(db, trigger, others, today)
    out = []
    for tier in ("CONFLICT", "DUPLICATE", "RELATED"):
        tier_pairs = [p for p in pairs if p["tier"] == tier]
        if not tier_pairs:
            continue
        alert_id, created = _persist(db, inst, tier, trigger, tier_pairs, trigger_type, trigger_action, actor, today)
        if alert_id:
            out.append({"alert_id": alert_id, "tier": tier, "created": created,
                        "cases": sorted({p["b"] for p in tier_pairs} | {case_id})})
    return out


def scan_all(db, *, actor: User | None = None, today: date | None = None) -> dict[str, int]:
    """Batch scan (seed, imports, on demand): every open case and every recent regulatory action."""
    today = today or clock_today()
    cfg = get_settings_block(db, "conflict")
    window = (today - timedelta(days=int(cfg["action_window_days"]))).isoformat()
    kinds = cfg["favourable_actions"] + cfg["adverse_actions"]
    km = ",".join("?" for _ in kinds)
    triggers = db.all(
        f"SELECT DISTINCT c.id, c.received_date FROM complaints c WHERE c.institution_id IS NOT NULL AND "
        f"(c.status != 'DISPOSED' OR c.id IN (SELECT case_id FROM case_actions WHERE action_type IN ({km}) "
        f"AND action_at >= ?)) ORDER BY c.received_date, c.id", (*kinds, window))
    created = updated = 0
    for t in triggers:
        for r in detect_for_case(db, t["id"], trigger_type="SCAN", actor=actor, today=today):
            if r["created"]:
                created += 1
            else:
                updated += 1
    return {"triggers": len(triggers), "created": created, "updated": updated}
