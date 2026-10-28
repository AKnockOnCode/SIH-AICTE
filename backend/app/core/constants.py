"""Shared vocabularies (statuses, outcomes, action types, channels)."""

from __future__ import annotations

STATUSES = ["RECEIVED", "PENDING", "UNDER_PROCESS", "TRANSFERRED", "ESCALATED", "DISPOSED"]
OPEN_STATUSES = ["RECEIVED", "PENDING", "UNDER_PROCESS", "TRANSFERRED", "ESCALATED"]
STATUS_LABELS = {
    "RECEIVED": "Received",
    "PENDING": "Pending",
    "UNDER_PROCESS": "Under process",
    "TRANSFERRED": "Transferred",
    "ESCALATED": "Escalated",
    "DISPOSED": "Disposed",
}

# Allowed manual status transitions (transfer/escalate/dispose have dedicated operations).
STATUS_TRANSITIONS = {
    "RECEIVED": {"PENDING", "UNDER_PROCESS"},
    "PENDING": {"UNDER_PROCESS"},
    "UNDER_PROCESS": {"PENDING"},
    "TRANSFERRED": {"PENDING", "UNDER_PROCESS"},
    "ESCALATED": {"UNDER_PROCESS"},
    "DISPOSED": set(),  # re-opening is a dedicated, audited operation
}

OUTCOMES = ["SUBSTANTIATED", "PARTIALLY_SUBSTANTIATED", "UNSUBSTANTIATED", "WITHDRAWN",
            "NOT_MAINTAINABLE", "PROCESS_COMPLETED"]
OUTCOME_LABELS = {
    "SUBSTANTIATED": "Substantiated",
    "PARTIALLY_SUBSTANTIATED": "Partially substantiated",
    "UNSUBSTANTIATED": "Unsubstantiated",
    "WITHDRAWN": "Withdrawn",
    "NOT_MAINTAINABLE": "Not maintainable",
    "PROCESS_COMPLETED": "Process completed (regulatory file)",
}

REFERENCE_FLAGS = ["NONE", "COURT", "VIP", "PARLIAMENT"]
COMPLAINANT_TYPES = ["STUDENT", "PARENT", "FACULTY", "STAFF", "OTHER", "ANONYMOUS"]
MATCH_STATUSES = ["CONFIRMED", "AUTO_LINKED", "PENDING_REVIEW", "UNMATCHED"]

CHANNELS = {
    "PGRC_PORTAL": "PGRC online portal",
    "CPGRAMS": "CPGRAMS feed",
    "RB_PORTAL": "RB portal",
    "EMAIL": "Email",
    "POST": "Post / PDF letter",
    "REGIONAL_OFFICE": "Regional office",
    "IMPORT": "Spreadsheet import",
    "INTAKE": "AgniDrishti intake form",
}

ACTION_TYPES: dict[str, str] = {
    "CREATED": "Case registered",
    "ACKNOWLEDGED": "Acknowledged",
    "ASSIGNED": "Assigned to officer",
    "NOTICE_ISSUED": "Notice issued to institution",
    "INSTITUTION_REPLY_RECEIVED": "Institution reply received",
    "INSPECTION_ORDERED": "Inspection / fact-finding ordered",
    "HEARING_HELD": "Hearing held",
    "SCRUTINY_COMPLETED": "Scrutiny completed",
    "REMARK": "Remark added",
    "DOCUMENT_ADDED": "Document reference added",
    "STATUS_CHANGED": "Status changed",
    "TRANSFERRED": "Transferred to another Bureau/Cell",
    "ESCALATED": "Escalated",
    "DEESCALATED": "Escalation reviewed",
    "DISPOSED": "Disposed",
    "REOPENED": "Re-opened",
    "PRIORITY_OVERRIDE": "Priority overridden",
    "LINKED": "Linked to another case",
    "UNLINKED": "Link removed",
    "MERGED_INTO_MASTER": "Merged into Master Case",
    "REMOVED_FROM_MASTER": "Removed from Master Case",
    "COORDINATION_NOTE": "Coordination decision recorded",
    "INSTITUTION_MATCH": "Institution match decided",
    "RENEWAL_INITIATED": "Approval renewal (EoA) initiated",
    "EXTENSION_OF_APPROVAL": "Extension of Approval granted",
    "APPROVAL_GRANTED": "Approval granted",
    "INTAKE_INCREASE_PROPOSED": "Intake increase proposed",
    "INTAKE_INCREASE_APPROVED": "Intake increase approved",
    "NOC_ISSUED": "NOC issued",
    "SHOW_CAUSE_NOTICE": "Show-cause notice issued",
    "CLOSURE_ORDER": "Closure order issued",
    "WITHDRAWAL_OF_APPROVAL": "Withdrawal of approval",
    "PENALTY_IMPOSED": "Penalty imposed",
}

# Actions an officer can add directly from the case screen (others come from dedicated operations).
MANUAL_ACTIONS = ["REMARK", "NOTICE_ISSUED", "INSTITUTION_REPLY_RECEIVED", "INSPECTION_ORDERED",
                  "HEARING_HELD", "SCRUTINY_COMPLETED"]
REGULATORY_ACTIONS = ["RENEWAL_INITIATED", "EXTENSION_OF_APPROVAL", "APPROVAL_GRANTED",
                      "INTAKE_INCREASE_PROPOSED", "INTAKE_INCREASE_APPROVED", "NOC_ISSUED",
                      "SHOW_CAUSE_NOTICE", "CLOSURE_ORDER", "WITHDRAWAL_OF_APPROVAL", "PENALTY_IMPOSED"]

PRIORITY_BANDS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
OVERLAP_TIERS = ["DUPLICATE", "RELATED", "CONFLICT"]
OVERLAP_STATUSES = ["OPEN", "UNDER_REVIEW", "RESOLVED", "DISMISSED"]
COORDINATION_HEADLINE = "Potential Overlapping Cases – Coordination Required"

ALERT_TYPES = ["OVERLAP", "SLA_WARNING", "SLA_OVERDUE", "PENDING_REMINDER", "PREDICTED_BREACH",
               "ESCALATION", "MATCH_REVIEW", "AUDIT_WARNING"]
ALERT_STATES = ["NEW", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]
SYNTHETIC_DISCLAIMER = (
    "SYNTHETIC DEMO DATA: institutions, complaints, officers and outcomes in this prototype are "
    "generated for demonstration. They are not real AICTE records or findings."
)
MIXED_DISCLAIMER = (
    "MIXED DATA: this instance holds SYNTHETIC demo records (generated for demonstration; not real AICTE "
    "records or findings) together with records entered or imported by users. Check each record's provenance."
)
