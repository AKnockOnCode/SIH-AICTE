"""Render the dossier to PDF with ReportLab (local, offline)."""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

NAVY = colors.HexColor("#1F3864")
BLUE = colors.HexColor("#0071C1")
RED = colors.HexColor("#D64545")
LIGHT = colors.HexColor("#EAF2FB")
GRID = colors.HexColor("#C9D3E3")


def _esc(text: Any) -> str:
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("₹", "Rs ")


def render(d: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"AgniDrishti dossier — {d['institution']['name']}", author="AgniDrishti prototype")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], textColor=NAVY, fontSize=16, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY, fontSize=11.5, spaceBefore=8, spaceAfter=3)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.6, leading=11, alignment=TA_LEFT)
    small = ParagraphStyle("s", parent=body, fontSize=7.4, leading=9.2, textColor=colors.HexColor("#4A5568"))
    warn = ParagraphStyle("w", parent=body, textColor=RED, fontSize=8.2, leading=10.5)
    story: list[Any] = []

    def table(rows: list[list[Any]], widths: list[float], header: bool = True) -> Table:
        data = [[Paragraph(_esc(c), small if i else body) if not isinstance(c, Paragraph) else c for c in r]
                for i, r in enumerate(rows)]
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        style = [("GRID", (0, 0), (-1, -1), 0.4, GRID), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]
        if header:
            style += [("BACKGROUND", (0, 0), (-1, 0), LIGHT)]
        t.setStyle(TableStyle(style))
        return t

    i, s, risk = d["institution"], d["summary"], d["risk"]
    story.append(Paragraph("AgniDrishti · Pre-Decision Dossier", h1))
    story.append(Paragraph(f"<b>{_esc(i['name'])}</b> — {_esc(i['permanent_id'] or 'no Permanent ID')} · {_esc(i['district'])}, "
                           f"{_esc(i['state'])} ({_esc(i['region'])} region)", body))
    story.append(Spacer(1, 3))
    story.append(Paragraph(_esc(d["disclaimer"]), warn))
    story.append(Paragraph("Summary", h2))
    nar = d["narrative"]
    story.append(Paragraph(_esc(nar["text"]), body))
    story.append(Paragraph(f"Narrative source: {_esc(nar['source'])}"
                           + (f" — {_esc(nar['validation'].get('note'))}" if nar.get("validation") else ""), small))
    story.append(Paragraph("Institution profile", h2))
    prof = [["Field", "Value"], ["Permanent ID", i["permanent_id"]], ["Address", f"{i['address'] or ''}, {i['district']}, {i['state']} "
                                                                         f"{i['pincode'] or ''}"],
            ["Trust / society", f"{i['trust'] or '—'}" + (f" ({i['trust_provenance']})" if i["trust"] else "")],
            ["Intake", f"{i['intake_total'] or 'unknown'} (source: {i['intake_source'] or 'n/a'})"],
            ["Courses", ", ".join(i["courses"]) or "—"], ["Aliases", "; ".join(d["aliases"]) or "—"],
            ["Synthetic record", "Yes" if i["synthetic"] else "No"]]
    story.append(table(prof, [38 * mm, 144 * mm]))
    story.append(Paragraph(f"Open cases and responsibility ({s['open_cases']} open, {s['overdue_open']} overdue)", h2))
    rows = [["Case", "Category (sev.)", "Bureau / officer", "Status / SLA", "Last action", "Next action", "Breach risk"]]
    for c in d["open_cases"]:
        rows.append([c["id"], f"{c['category']} ({c['severity']}/5)", f"{c['bureau']} / {c['officer']}", f"{c['status']} · {c['sla']}",
                     f"{c['last_action'] or ''} ({c['last_action_at']})", f"{c['next_action'] or ''} (due {c['next_action_due'] or '—'})",
                     "fact: overdue" if c["sla_state"] == "OVERDUE" else
                     (f"{round(c['breach_probability'] * 100)}% ({c['breach_band']})" if c["breach_probability"] is not None else "—")])
    story.append(table(rows, [18 * mm, 27 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm, 17 * mm]))
    story.append(Paragraph("Duplicate / related / conflict alerts", h2))
    if d["overlaps"]:
        rows = [["Alert", "Tier / headline", "Cases", "Why (rules)", "Lead", "Next step"]]
        for o in d["overlaps"]:
            rows.append([o["id"], f"{o['tier']}: {o['headline']}", ", ".join(o["cases"]), "; ".join(o["rules"][:3]),
                         f"{o['decided_lead'] or o['recommended_lead']} ({'agreed' if o['decided_lead'] else 'recommended'})",
                         o["next_step"]])
        story.append(table(rows, [16 * mm, 34 * mm, 28 * mm, 48 * mm, 20 * mm, 36 * mm]))
    else:
        story.append(Paragraph("No open overlap alerts.", body))
    if risk:
        fc = risk["forecast"]
        comp = risk["components"]
        story.append(KeepTogether([
            Paragraph("Institution Risk Index and forecast", h2),
            table([["Measure", "Value", "Explanation"],
                   ["Risk Index", f"{risk['score']:.0f}/100 ({risk['band']})", f"{risk['trend']} ({risk['delta_6m']:+.0f} in 6 months); "
                                                                               f"confidence {risk['confidence']}"],
                   ["Severity-weighted load", f"{comp['severity_weighted_load']:.1f}", f"{comp['cases_considered']} complaints; "
                    f"{round(comp['recent_12m_share'] * 100)}% from last 12 months; half-life {comp['half_life_days']} days"],
                   ["Normalisation", f"{comp['exposure_thousand_students']:.2f} k students",
                    "intake known" if comp["intake_known"] else "fallback intake (reduced confidence)"],
                   ["Shrinkage", f"credibility {round(comp['credibility'] * 100)}%", f"raw rate {comp['raw_rate']:.2f} -> shrunk "
                    f"{comp['shrunk_rate']:.2f} (population {comp['population_rate']:.2f})"],
                   ["Serious complaint, next 6 months", f"{round(fc['probability'] * 100)}% (80% range {round(fc['interval_80'][0] * 100)}"
                    f"–{round(fc['interval_80'][1] * 100)}%)", f"{fc['status']} · {fc['confidence']} confidence · trend {fc['trend']} · "
                    f"{fc['n_events']} serious events"]],
                  [44 * mm, 40 * mm, 98 * mm]),
            Paragraph("Caveats: " + _esc(" ".join(risk["caveats"])), small)]))
    story.append(Paragraph("Pending SLAs, predicted breaches and escalations", h2))
    story.append(Paragraph(f"Overdue/due soon: {', '.join(c['id'] for c in d['pending_sla']) or 'none'}. Predicted breaches "
                           f"(model): {', '.join(c['id'] for c in d['predicted_breaches']) or 'none'}. Escalated: "
                           f"{', '.join(c['id'] for c in d['escalations']) or 'none'}.", body))
    story.append(Paragraph("Coordination recommendations", h2))
    for r in d["recommendations"]:
        story.append(Paragraph("• " + _esc(r), body))
    story.append(Paragraph("Recent actions", h2))
    rows = [["When", "Case", "Action", "By", "Remarks"]]
    for a in d["recent_actions"][:12]:
        rows.append([a["action_at"][:10], a["case_id"], a["label"], a["actor_label"], (a["remarks"] or "")[:120]])
    story.append(table(rows, [20 * mm, 20 * mm, 38 * mm, 38 * mm, 66 * mm]))
    story.append(Paragraph(f"Case history ({len(d['case_history'])} records)", h2))
    rows = [["Case", "Received", "Category", "Bureau", "Status", "Outcome"]]
    for c in d["case_history"][:40]:
        rows.append([c["id"], c["received"], c["category"], c["bureau"], c["status"], c["outcome"] or "—"])
    story.append(table(rows, [20 * mm, 22 * mm, 52 * mm, 16 * mm, 30 * mm, 42 * mm]))
    p = d["provenance"]
    story.append(Paragraph("Provenance", h2))
    story.append(Paragraph(_esc(f"Generated {p['generated_at']} by {p['generated_by']} (as of {p['as_of']}, app v{p['app_version']}). "
                                f"Data: {p['data']}. Seed: {p['seed']}. Methods: risk — {p['risk_method']}; forecast — "
                                f"{p['forecast_method']}; breach — {p['breach_method']}."), small))

    footer_label = ("MIXED DATA — synthetic demo records plus user-entered/imported records · AgniDrishti prototype"
                    if str(d["disclaimer"]).startswith("MIXED") else
                    "SYNTHETIC DEMO DATA — not real AICTE records · AgniDrishti prototype")

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(RED)
        canvas.drawString(14 * mm, 8 * mm, footer_label)
        canvas.setFillColor(colors.grey)
        canvas.drawRightString(196 * mm, 8 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
