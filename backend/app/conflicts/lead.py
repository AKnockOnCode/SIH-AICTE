"""Lead Bureau/Cell recommendation for a group of overlapping cases (advisory only).

score(b) = (subject_points + handler_points + action_points) x workload_factor
  subject_points  sum of severity weights of member cases whose category is normally handled
                  by b (open cases count fully, disposed context cases at half weight)
  handler_points  current_handler_weight x severity weight of open cases currently held by b
  action_points   regulatory_action_weight for each favourable/adverse regulatory action
                  taken by b on a member case within the action window
  workload_factor clamp(1 - sensitivity x (load_ratio - 1), min, max) where load_ratio is b's
                  open cases per officer divided by the average across Bureaus/Cells
The highest score is recommended with a written rationale. Officers with authority accept
or override it (both audited); nothing is reassigned automatically.
"""

from __future__ import annotations

from typing import Any

from ..core.util import clamp


def workload(db) -> dict[str, dict[str, float]]:
    officers = {r["bureau_code"]: r["n"] for r in db.all(
        "SELECT bureau_code, COUNT(*) n FROM officers WHERE active = 1 GROUP BY bureau_code")}
    open_counts = {r["bureau_code"]: r["n"] for r in db.all(
        "SELECT bureau_code, COUNT(*) n FROM complaints WHERE status != 'DISPOSED' GROUP BY bureau_code")}
    names = {r["code"]: r["name"] for r in db.all("SELECT code, name FROM bureaus")}
    out: dict[str, dict[str, float]] = {}
    for b in names:
        off = officers.get(b, 0)
        opn = open_counts.get(b, 0)
        out[b] = {"open": opn, "officers": off, "open_per_officer": opn / off if off else float(opn)}
    vals = [v["open_per_officer"] for v in out.values() if v["officers"]]
    mean = sum(vals) / len(vals) if vals else 1.0
    for v in out.values():
        v["load_ratio"] = v["open_per_officer"] / mean if mean else 1.0
    return out


def recommend(db, members: list[dict[str, Any]], rules: dict[str, Any], cfg: dict[str, Any],
              reg_actions: dict[str, list[dict[str, Any]]], load: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    load = load or workload(db)
    names = {r["code"]: r["name"] for r in db.all("SELECT code, name FROM bureaus")}
    subject: dict[str, float] = {}
    handler: dict[str, float] = {}
    action: dict[str, float] = {}
    notes: dict[str, list[str]] = {}
    for m in members:
        rule = rules[m["category_code"]]
        sev = float(rule["severity_weight"])
        is_open = m["status"] != "DISPOSED"
        comp = rule["default_bureau"]
        pts = float(cfg["competence_weight"]) * sev * (1.0 if is_open else 0.5)
        subject[comp] = subject.get(comp, 0.0) + pts
        notes.setdefault(comp, []).append(f"{m['id']} ({rule['label']}, {'open' if is_open else 'disposed context'}) "
                                          f"is normally handled by {comp}: +{pts:.1f}")
        if is_open:
            h = float(cfg["current_handler_weight"]) * sev
            handler[m["bureau_code"]] = handler.get(m["bureau_code"], 0.0) + h
            notes.setdefault(m["bureau_code"], []).append(f"currently holds open case {m['id']}: +{h:.1f}")
        for act in reg_actions.get(m["id"], []):
            b = act.get("bureau_code") or m["bureau_code"]
            a = float(cfg["regulatory_action_weight"])
            action[b] = action.get(b, 0.0) + a
            notes.setdefault(b, []).append(f"took regulatory action {act['action_type']} on {m['id']}: +{a:.1f}")
    candidates = sorted(set(subject) | set(handler) | set(action))
    rows = []
    for b in candidates:
        lv = load.get(b, {"open": 0, "officers": 0, "open_per_officer": 0.0, "load_ratio": 1.0})
        factor = clamp(1.0 - float(cfg["workload_sensitivity"]) * (lv["load_ratio"] - 1.0),
                       float(cfg["workload_min_factor"]), float(cfg["workload_max_factor"]))
        base = subject.get(b, 0.0) + handler.get(b, 0.0) + action.get(b, 0.0)
        rows.append({
            "bureau": b, "bureau_name": names.get(b, b), "subject_points": round(subject.get(b, 0.0), 2),
            "handler_points": round(handler.get(b, 0.0), 2), "action_points": round(action.get(b, 0.0), 2),
            "open_cases": int(lv["open"]), "officers": int(lv["officers"]),
            "open_per_officer": round(lv["open_per_officer"], 1), "load_ratio": round(lv["load_ratio"], 2),
            "workload_factor": round(factor, 2), "score": round(base * factor, 2), "notes": notes.get(b, []),
        })
    rows.sort(key=lambda r: (-r["score"], r["load_ratio"], r["bureau"]))
    if not rows:
        return {"recommended": None, "scores": [], "rationale": ["No candidate Bureau/Cell."], "advisory": True}
    top = rows[0]
    rationale = [
        f"{top['bureau_name']} ({top['bureau']}) scores highest: subject-matter {top['subject_points']:.1f} + "
        f"current handling {top['handler_points']:.1f} + regulatory actions {top['action_points']:.1f}, "
        f"x workload factor {top['workload_factor']:.2f} ({top['open_per_officer']:.1f} open cases/officer, "
        f"{top['load_ratio']:.2f}x the average) = {top['score']:.1f}.",
    ]
    for r in rows[1:3]:
        rationale.append(f"{r['bureau']} scores {r['score']:.1f} (subject {r['subject_points']:.1f}, handling "
                         f"{r['handler_points']:.1f}, actions {r['action_points']:.1f}, workload x{r['workload_factor']:.2f}).")
    rationale.append("Recommendation only: an authorised officer accepts or overrides it; no case is reassigned automatically.")
    return {"recommended": top["bureau"], "recommended_name": top["bureau_name"], "scores": rows,
            "rationale": rationale, "advisory": True}
