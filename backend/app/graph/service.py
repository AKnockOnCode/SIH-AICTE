"""Trust/Society graph with NetworkX.

Nodes: trusts/societies and institutions; edges: OPERATED_BY (trust -> institution) taken
only from stored relationships (`institutions.trust_id`, with its provenance). No common
trust is ever inferred from similar names. Institution nodes carry open/overdue counts,
open overlap alerts and the risk index; trust nodes carry group aggregates and
group-pattern flags computed from the graph.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import networkx as nx

from ..core.security import User, region_scope
from ..risk import index as risk_index


def build(db, user: User, today: date, min_members: int = 1, trust_id: str | None = None) -> dict[str, Any]:
    risk = risk_index.compute_all(db, today)["institutions"]
    insts = db.all("SELECT id, name, state, district, region_code, trust_id, trust_relation_source, is_synthetic, demo_tag "
                   "FROM institutions")
    trusts = {t["id"]: t for t in db.all("SELECT * FROM trusts")}
    counts = {r["institution_id"]: r for r in db.all(
        "SELECT institution_id, SUM(status != 'DISPOSED') AS open_cases, "
        "SUM(status != 'DISPOSED' AND expected_disposal_date < ?) AS overdue, COUNT(*) AS total, "
        "COUNT(DISTINCT CASE WHEN status != 'DISPOSED' THEN bureau_code END) AS open_bureaus "
        "FROM complaints WHERE institution_id IS NOT NULL GROUP BY institution_id", (today.isoformat(),))}
    overlaps = {r["institution_id"]: r for r in db.all(
        "SELECT institution_id, COUNT(*) AS open_alerts, SUM(tier = 'CONFLICT') AS conflicts FROM overlap_alerts "
        "WHERE status IN ('OPEN','UNDER_REVIEW') GROUP BY institution_id")}
    scope = region_scope(user)
    g = nx.DiGraph()  # edges are directed trust -> institution
    for i in insts:
        if scope and i["region_code"] != scope:
            continue
        r = risk.get(i["id"], {})
        c = counts.get(i["id"], {})
        o = overlaps.get(i["id"], {})
        flagged_reasons = []
        if r.get("band") == "HIGH":
            flagged_reasons.append("high risk")
        if r.get("trend") == "RISING":
            flagged_reasons.append("rising risk")
        if (o.get("conflicts") or 0) > 0:
            flagged_reasons.append("open cross-bureau conflict")
        if (c.get("overdue") or 0) >= 3:
            flagged_reasons.append(f"{c.get('overdue')} overdue cases")
        g.add_node(f"I:{i['id']}", kind="institution", id=i["id"], label=i["name"], state=i["state"],
                   district=i["district"], region=i["region_code"], risk=r.get("score"), risk_band=r.get("band"),
                   trend=r.get("trend"), open_cases=int(c.get("open_cases") or 0), overdue=int(c.get("overdue") or 0),
                   total_cases=int(c.get("total") or 0), open_bureaus=int(c.get("open_bureaus") or 0),
                   open_overlaps=int(o.get("open_alerts") or 0), conflicts=int(o.get("conflicts") or 0),
                   flagged=bool(flagged_reasons), flag_reasons=flagged_reasons, demo_tag=i["demo_tag"],
                   synthetic=bool(i["is_synthetic"]))
        if i["trust_id"]:
            t = trusts[i["trust_id"]]
            tn = f"T:{t['id']}"
            if tn not in g:
                g.add_node(tn, kind="trust", id=t["id"], label=t["name"], state=t["state"], provenance=t["provenance"],
                           synthetic=bool(t["is_synthetic"]))
            g.add_edge(tn, f"I:{i['id']}", relation="OPERATED_BY", provenance=i["trust_relation_source"] or "UNKNOWN")
    groups = []
    for node, data in g.nodes(data=True):
        if data["kind"] != "trust":
            continue
        members = [g.nodes[n] for n in g.neighbors(node)]
        flagged = [m for m in members if m["flagged"]]
        states = sorted({m["state"] for m in members})
        risks = [m["risk"] for m in members if m["risk"] is not None]
        patterns = []
        if len(flagged) >= 2:
            patterns.append(f"{len(flagged)} of {len(members)} institutions flagged")
        if len(states) > 1:
            patterns.append(f"operates across {len(states)} states")
        if sum(m["conflicts"] for m in members) >= 1:
            patterns.append("cross-bureau conflict open at a member institution")
        data.update(members=len(members), flagged_members=len(flagged),
                    open_cases=sum(m["open_cases"] for m in members), overdue=sum(m["overdue"] for m in members),
                    avg_risk=round(sum(risks) / len(risks), 1) if risks else None, max_risk=max(risks) if risks else None,
                    patterns=patterns, flagged=len(flagged) >= 2)
        groups.append({"trust_id": data["id"], "name": data["label"], "members": len(members),
                       "flagged_members": len(flagged), "open_cases": data["open_cases"], "overdue": data["overdue"],
                       "avg_risk": data["avg_risk"], "max_risk": data["max_risk"], "states": states, "patterns": patterns,
                       "provenance": data["provenance"], "institutions": sorted(m["id"] for m in members)})
    groups.sort(key=lambda x: (-x["flagged_members"], -(x["avg_risk"] or 0)))
    if trust_id:
        keep = {f"T:{trust_id}"} | set(g.neighbors(f"T:{trust_id}")) if f"T:{trust_id}" in g else set()
        g = g.subgraph(keep).copy()
    elif min_members > 1:
        drop = [n for n, d in g.nodes(data=True) if d["kind"] == "institution" and g.degree(n) == 0]
        g.remove_nodes_from(drop)
    components = [sorted(c) for c in nx.weakly_connected_components(g)]
    nodes = [{"key": n, **{k: v for k, v in d.items()}} for n, d in g.nodes(data=True)]
    edges = [{**d, "source": u, "target": v} for u, v, d in g.edges(data=True)]
    return {
        "nodes": nodes, "edges": edges, "groups": groups,
        "stats": {"institutions": sum(1 for n in nodes if n["kind"] == "institution"),
                  "trusts": sum(1 for n in nodes if n["kind"] == "trust"), "edges": len(edges),
                  "components": len(components),
                  "standalone_institutions": sum(1 for n in nodes if n["kind"] == "institution" and g.degree(n["key"]) == 0)},
        "legend": {
            "trust": "Trust / society / management group (synthetic relationship data)",
            "institution": "Institution (size = open cases; colour = risk band)",
            "OPERATED_BY": "Edge: the trust operates the institution (stored relationship, never inferred from names)",
            "flagged": "Red ring: high/rising risk, open cross-bureau conflict or 3+ overdue cases",
        },
        "provenance": "All trust relationships in this demo dataset are SYNTHETIC (generated), not real records.",
    }
