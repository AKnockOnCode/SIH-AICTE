"""Reference data: regions, states, Bureaus/Cells, officers and demo users.

The region grouping below is a DEMO grouping of states into AICTE-style regions. AICTE's
actual Regional Office jurisdictions were not retrievable during the build, so this mapping
must be validated against AICTE records before any real use (see README, Assumptions).
The Bureau/Cell list is likewise configurable demo reference data.
"""

from __future__ import annotations

REGIONS: list[tuple[str, str]] = [
    ("NORTHERN", "Northern"),
    ("NORTH_WESTERN", "North-Western"),
    ("CENTRAL", "Central"),
    ("WESTERN", "Western"),
    ("EASTERN", "Eastern"),
    ("NORTH_EASTERN", "North-Eastern"),
    ("SOUTHERN", "Southern"),
    ("SOUTH_WESTERN", "South-Western"),
    ("SOUTH_CENTRAL", "South-Central"),
]

# state -> (region, [(district, pincode prefix)])
STATES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "Maharashtra": ("WESTERN", [("Pune", "411"), ("Nagpur", "440"), ("Nashik", "422"), ("Kolhapur", "416"), ("Chhatrapati Sambhajinagar", "431")]),
    "Gujarat": ("WESTERN", [("Ahmedabad", "380"), ("Vadodara", "390"), ("Surat", "395"), ("Rajkot", "360")]),
    "Goa": ("WESTERN", [("North Goa", "403")]),
    "Madhya Pradesh": ("CENTRAL", [("Bhopal", "462"), ("Indore", "452"), ("Jabalpur", "482"), ("Gwalior", "474")]),
    "Chhattisgarh": ("CENTRAL", [("Raipur", "492"), ("Bilaspur", "495")]),
    "Uttar Pradesh": ("NORTHERN", [("Lucknow", "226"), ("Kanpur Nagar", "208"), ("Gautam Buddh Nagar", "201"), ("Varanasi", "221"), ("Prayagraj", "211")]),
    "Uttarakhand": ("NORTHERN", [("Dehradun", "248")]),
    "Delhi": ("NORTH_WESTERN", [("New Delhi", "110")]),
    "Haryana": ("NORTH_WESTERN", [("Gurugram", "122"), ("Faridabad", "121")]),
    "Punjab": ("NORTH_WESTERN", [("Ludhiana", "141"), ("SAS Nagar", "160"), ("Jalandhar", "144")]),
    "Rajasthan": ("NORTH_WESTERN", [("Jaipur", "302"), ("Jodhpur", "342"), ("Kota", "324")]),
    "Himachal Pradesh": ("NORTH_WESTERN", [("Shimla", "171")]),
    "West Bengal": ("EASTERN", [("Kolkata", "700"), ("Paschim Bardhaman", "713")]),
    "Odisha": ("EASTERN", [("Khordha", "751"), ("Cuttack", "753")]),
    "Bihar": ("EASTERN", [("Patna", "800")]),
    "Jharkhand": ("EASTERN", [("Ranchi", "834")]),
    "Assam": ("NORTH_EASTERN", [("Kamrup Metropolitan", "781")]),
    "Meghalaya": ("NORTH_EASTERN", [("East Khasi Hills", "793")]),
    "Tamil Nadu": ("SOUTHERN", [("Chennai", "600"), ("Coimbatore", "641"), ("Madurai", "625"), ("Tiruchirappalli", "620")]),
    "Kerala": ("SOUTHERN", [("Thiruvananthapuram", "695"), ("Ernakulam", "682"), ("Kozhikode", "673")]),
    "Puducherry": ("SOUTHERN", [("Puducherry", "605")]),
    "Karnataka": ("SOUTH_WESTERN", [("Bengaluru Urban", "560"), ("Mysuru", "570"), ("Belagavi", "590"), ("Dakshina Kannada", "575")]),
    "Telangana": ("SOUTH_CENTRAL", [("Hyderabad", "500"), ("Warangal", "506")]),
    "Andhra Pradesh": ("SOUTH_CENTRAL", [("Visakhapatnam", "530"), ("NTR", "520"), ("Guntur", "522"), ("Tirupati", "517")]),
}

BUREAUS: list[tuple[str, str, str, str]] = [
    ("RB", "Regulation Bureau", "BUREAU", "Regulatory concerns, approvals/renewals oversight and compliance actions"),
    ("PGRC", "Public Grievance Redressal Cell", "CELL", "Student, parent and stakeholder grievances"),
    ("AB", "Approval Bureau", "BUREAU", "Approval process matters (demo bureau)"),
    ("SDC", "Student Development Cell", "CELL", "Scholarship and student-support matters (demo cell)"),
    ("LC", "Legal Cell", "CELL", "Court-referenced and legal matters (demo cell)"),
    ("RO", "Regional Offices", "REGIONAL", "Cases handled at AICTE Regional Offices/Centres"),
]

# Officers are identified by designation codes only (no personal names are stored).
OFFICER_COUNTS: dict[str, int] = {"RB": 6, "PGRC": 8, "AB": 3, "SDC": 4, "LC": 3}
OFFICER_TITLES: dict[str, str] = {
    "RB": "RB Desk Officer",
    "PGRC": "PGRC Grievance Officer",
    "AB": "Approval Desk Officer",
    "SDC": "SDC Desk Officer",
    "LC": "Legal Officer",
    "RO": "Regional Officer",
}

DEMO_USERS: list[dict[str, str | None]] = [
    {"id": "competent.authority", "display_name": "Competent Authority (demo)", "role": "COMPETENT_AUTHORITY",
     "bureau_code": None, "region_code": None, "officer_id": None,
     "description": "Reviews escalations, final cross-bureau conflict decisions, rule changes."},
    {"id": "rb.officer", "display_name": "RB Officer (demo)", "role": "RB_OFFICER",
     "bureau_code": "RB", "region_code": None, "officer_id": "OFF-RB-01",
     "description": "Works Regulation Bureau cases; can initiate regulatory actions."},
    {"id": "pgrc.officer", "display_name": "PGRC Officer (demo)", "role": "PGRC_OFFICER",
     "bureau_code": "PGRC", "region_code": None, "officer_id": "OFF-PGRC-03",
     "description": "Works Public Grievance Redressal Cell cases."},
    {"id": "ro.central", "display_name": "Regional Office – Central (demo)", "role": "REGIONAL_OFFICE",
     "bureau_code": "RO", "region_code": "CENTRAL", "officer_id": "OFF-RO-CENTRAL",
     "description": "Sees Central-region institutions and cases; adds remarks, documents, escalations."},
    {"id": "senior.mgmt", "display_name": "Senior Management (demo)", "role": "SENIOR_MANAGEMENT",
     "bureau_code": None, "region_code": None, "officer_id": None,
     "description": "Read-only oversight of analytics, workload, risk and cross-bureau status."},
]


def seed_reference(db, now: str) -> None:
    """Insert reference rows (idempotent: INSERT OR IGNORE)."""
    for i, (code, name) in enumerate(REGIONS):
        db.run("INSERT OR IGNORE INTO regions(code, name, sort_order) VALUES (?,?,?)", (code, name, i))
    for state, (region, _d) in STATES.items():
        db.run("INSERT OR IGNORE INTO states(name, region_code) VALUES (?,?)", (state, region))
    for i, (code, name, kind, desc) in enumerate(BUREAUS):
        db.run("INSERT OR IGNORE INTO bureaus(code, name, kind, description, sort_order) VALUES (?,?,?,?,?)",
               (code, name, kind, desc, i))
    for bureau, n in OFFICER_COUNTS.items():
        for k in range(1, n + 1):
            db.run(
                "INSERT OR IGNORE INTO officers(id, display_name, designation, bureau_code) VALUES (?,?,?,?)",
                (f"OFF-{bureau}-{k:02d}", f"{OFFICER_TITLES[bureau]} {k:02d}", OFFICER_TITLES[bureau], bureau),
            )
    for code, name in REGIONS:
        db.run(
            "INSERT OR IGNORE INTO officers(id, display_name, designation, bureau_code, region_code) VALUES (?,?,?,?,?)",
            (f"OFF-RO-{code}", f"Regional Officer ({name})", OFFICER_TITLES["RO"], "RO", code),
        )
    for i, u in enumerate(DEMO_USERS):
        db.run(
            "INSERT OR IGNORE INTO demo_users(id, display_name, role, bureau_code, region_code, officer_id, description, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (u["id"], u["display_name"], u["role"], u["bureau_code"], u["region_code"], u["officer_id"], u["description"], i),
        )
