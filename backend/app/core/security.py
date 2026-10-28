"""Demo roles, permission matrix and object-level access rules.

IMPORTANT: this is a *prototype role simulation*. The active demo user is chosen with the
`X-Demo-User` header (the UI's role switcher). There is no password or identity proof;
production deployment needs real authentication (e.g. SSO) in front of these checks.
Every protected route and every object-level decision below runs on the server.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import ApiError, forbidden

ROLE_LABELS: dict[str, str] = {
    "RB_OFFICER": "RB Officer",
    "PGRC_OFFICER": "PGRC Officer",
    "REGIONAL_OFFICE": "Regional Office",
    "SENIOR_MANAGEMENT": "Senior Management",
    "COMPETENT_AUTHORITY": "Competent Authority",
}

PERMISSION_DESCRIPTIONS: dict[str, str] = {
    "dashboard.view": "View command dashboard",
    "institution.view": "View institution master and profiles",
    "case.view": "View cases and timelines",
    "overlap.view": "View overlap/conflict alerts",
    "alert.view": "View alerts centre",
    "risk.view": "View risk index, forecast and watch-list",
    "graph.view": "View trust/society graph",
    "report.view": "View reports and analytics",
    "dossier.view": "Generate pre-decision dossier",
    "signals.view": "View public signals",
    "rules.view": "View priority/SLA/matching rules",
    "audit.view": "View audit trail and system status",
    "import.view": "View import jobs and templates",
    "case.create": "Register a new complaint/case",
    "case.update": "Status change, assignment and actions on permitted cases",
    "case.transfer": "Transfer a case to another Bureau/Cell",
    "case.escalate": "Escalate a case",
    "case.dispose": "Dispose a case with outcome",
    "case.document": "Add document references",
    "case.priority_override": "Override computed priority (reason mandatory)",
    "match.review": "Confirm or reject institution matches",
    "overlap.act": "Link cases / mark overlap alert for review",
    "overlap.merge": "Merge eligible duplicates into a Master Case",
    "overlap.decide": "Accept or override lead-Bureau recommendation; resolve/dismiss alerts",
    "overlap.final": "Final resolution of cross-bureau CONFLICT alerts; cross-bureau merge; unmerge",
    "alert.act": "Acknowledge / resolve / dismiss alerts",
    "report.export": "Export reports (CSV/XLSX) and dossiers",
    "import.run": "Upload, validate and commit CSV/XLSX imports",
    "audit.verify": "Run hash-chain verification",
    "rules.edit": "Edit or reset priority, SLA, matching and conflict rules",
    "signals.import": "Import public signals",
    "system.sweep": "Re-run alert / detection sweeps",
}

VIEW_PERMS = frozenset(
    {
        "dashboard.view", "institution.view", "case.view", "overlap.view", "alert.view",
        "risk.view", "graph.view", "report.view", "dossier.view", "signals.view",
        "rules.view", "audit.view", "import.view",
    }
)

_OFFICER = VIEW_PERMS | {
    "case.create", "case.update", "case.transfer", "case.escalate", "case.dispose",
    "case.document", "case.priority_override", "match.review", "overlap.act",
    "overlap.merge", "overlap.decide", "alert.act", "report.export", "import.run",
    "audit.verify",
}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "RB_OFFICER": frozenset(_OFFICER),
    "PGRC_OFFICER": frozenset(_OFFICER),
    "REGIONAL_OFFICE": frozenset(
        VIEW_PERMS
        | {"case.create", "case.update", "case.escalate", "case.document", "match.review",
           "overlap.act", "alert.act", "report.export"}
    ),
    "SENIOR_MANAGEMENT": frozenset(VIEW_PERMS | {"report.export", "audit.verify"}),
    "COMPETENT_AUTHORITY": frozenset(set(PERMISSION_DESCRIPTIONS)),
}

# Case-level operations and who may perform them (object-level, enforced in services).
CASE_OPS = (
    "status", "assign", "transfer", "escalate", "deescalate", "dispose", "remark",
    "document", "priority_override", "regulatory_action",
)
REGULATORY_BUREAUS = {"RB", "AB"}


@dataclass(frozen=True)
class User:
    id: str
    display_name: str
    role: str
    bureau_code: str | None
    region_code: str | None
    officer_id: str | None

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def is_authority(self) -> bool:
        return self.role == "COMPETENT_AUTHORITY"

    def has(self, perm: str) -> bool:
        return perm in ROLE_PERMISSIONS.get(self.role, frozenset())

    def as_actor(self) -> dict[str, Any]:
        return {
            "actor_id": self.id,
            "actor_label": self.display_name,
            "actor_role": self.role,
            "actor_bureau": self.bureau_code,
        }


SYSTEM_USER = User(
    id="system", display_name="AgniDrishti system (automated)", role="SYSTEM",
    bureau_code=None, region_code=None, officer_id=None,
)


def resolve_user(db, user_id: str) -> User:
    row = db.one("SELECT * FROM demo_users WHERE id = ?", (user_id,))
    if row is None:
        raise ApiError(401, "unknown_demo_user", f"Unknown demo user '{user_id}'. Pick a role in the role switcher.")
    return User(
        id=row["id"], display_name=row["display_name"], role=row["role"],
        bureau_code=row["bureau_code"], region_code=row["region_code"], officer_id=row["officer_id"],
    )


def require(user: User, perm: str) -> None:
    if not user.has(perm):
        raise forbidden(
            f"Your demo role ({user.role_label}) is not permitted to perform '{perm}'.",
            {"permission": perm, "role": user.role},
        )


def region_scope(user: User) -> str | None:
    """Regional Office users only see institutions/cases of their own region."""
    return user.region_code if user.role == "REGIONAL_OFFICE" else None


def can_view_case(user: User, case: dict[str, Any]) -> bool:
    scope = region_scope(user)
    return scope is None or case.get("region_code") == scope


def assert_can_view_case(user: User, case: dict[str, Any]) -> None:
    if not can_view_case(user, case):
        raise forbidden(f"Case {case.get('id')} is outside your region ({user.region_code}).")


def can_view_institution(user: User, inst: dict[str, Any]) -> bool:
    scope = region_scope(user)
    return scope is None or inst.get("region_code") == scope


def assert_can_view_institution(user: User, inst: dict[str, Any]) -> None:
    if not can_view_institution(user, inst):
        raise forbidden(f"Institution {inst.get('id')} is outside your region ({user.region_code}).")


def allowed_case_ops(user: User, case: dict[str, Any]) -> set[str]:
    """Which workflow operations this user may perform on this case right now."""
    if user.role == "COMPETENT_AUTHORITY":
        return set(CASE_OPS)
    if user.role in ("RB_OFFICER", "PGRC_OFFICER"):
        if case.get("bureau_code") != user.bureau_code:
            return set()
        ops = {"status", "assign", "transfer", "escalate", "dispose", "remark", "document", "priority_override"}
        if user.bureau_code in REGULATORY_BUREAUS:
            ops.add("regulatory_action")
        return ops
    if user.role == "REGIONAL_OFFICE":
        if case.get("region_code") == user.region_code:
            return {"remark", "document", "escalate"}
        return set()
    return set()


def assert_case_op(user: User, case: dict[str, Any], op: str) -> None:
    if op not in allowed_case_ops(user, case):
        raise forbidden(
            f"{user.role_label} may not perform '{op}' on case {case.get('id')} "
            f"(case is with {case.get('bureau_code')}). Cross-bureau actions need coordination or escalation.",
            {"operation": op, "case_bureau": case.get("bureau_code"), "role": user.role},
        )


def permission_matrix() -> list[dict[str, Any]]:
    rows = []
    for perm, desc in PERMISSION_DESCRIPTIONS.items():
        rows.append({
            "permission": perm,
            "description": desc,
            "roles": {role: perm in perms for role, perms in ROLE_PERMISSIONS.items()},
        })
    return rows
