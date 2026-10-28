"""Generate the sample import files in backend/data/samples (python -m app.tools.make_samples).

They deliberately use non-standard headers (to exercise column mapping) and include invalid rows
(to exercise row-level validation). All content is synthetic.
"""

from __future__ import annotations

import csv
from pathlib import Path

import xlsxwriter

OUT = Path(__file__).resolve().parents[2] / "data" / "samples"

INSTITUTION_ROWS = [
    ["College Name", "AICTE ID", "State", "City", "PIN", "Total Intake", "Trust/Society", "Other names"],
    ["Kesari Institute of Technology", "SYN-1-49990001", "Maharashtra", "Pune", "411045", "540", "Kesari Education Trust", "KIT Pune"],
    ["Vasundhara College of Pharmacy", "", "MP", "Jabalpur", "482001", "120", "", ""],
    ["Sankalp Institute of Engg & Technology", "", "Madhya Pradesh", "Bhopal", "", "", "", "SIET"],
    ["Navankur Institute", "", "Maharashtra", "", "", "", "", ""],
    ["Example Polytechnic", "", "Atlantis", "Nowhere", "000000", "60", "", ""],
    ["", "SYN-1-49990009", "Kerala", "Kochi", "682001", "300", "", ""],
    ["Kesari Institute of Technology", "SYN-1-49990001", "Maharashtra", "Pune", "411045", "540", "Kesari Education Trust", ""],
    ["Godavari Institute of Management", "SYN-1-49990002", "TS", "Hyderabad", "5000AB", "abc", "", ""],
]

COMPLAINT_HEADER = ["Complaint No", "Name of Institution", "AICTE ID", "State", "Nature of Complaint", "Date of Receipt",
                    "Bureau/Cell", "Current Status", "Complaint Details", "No. of Complainants", "Evidence Attached",
                    "Disposed On", "Outcome", "Reference"]
COMPLAINT_ROWS = [
    ["IMP/PGRC/2026/001", "Sankalp Inst. of Engg. & Tech.", "", "Madhya Pradesh", "Fee refund", "20-10-2026", "PGRC", "Pending",
     "Hostel deposit of final-year students not refunded despite repeated requests to the accounts section.", 5, "yes", "", "", ""],
    ["IMP/PGRC/2026/002", "Prerana Institute of Technology & Science, Warangal", "", "Telangana", "Ragging", "22-10-2026", "PGRC",
     "New", "Juniors were forced by seniors to stay awake and run errands in the hostel; parents fear retaliation.", 2, "no", "",
     "", ""],
    ["IMP/RB/2026/003", "", "SYN-1-41730052", "", "Infrastructure", "15-09-2026", "Regulation Bureau", "Under process",
     "Laboratory equipment listed in the approval documents is missing in two departments.", 1, "2", "", "", ""],
    ["IMP/SDC/2026/004", "Udaan Institute of Technology", "", "Telangana", "Scholarship", "18-10-2026", "SDC", "Pending",
     "Scholarship applications of eligible students were not forwarded before the deadline.", 11, "yes", "", "", ""],
    ["IMP/PGRC/2026/005", "Abhyudaya College of Engineering & Research", "", "Maharashtra", "Examination", "31-02-2026", "PGRC",
     "Pending", "Results withheld for students who did not pay an extra examination fee.", 30, "yes", "", "", ""],
    ["IMP/PGRC/2026/006", "Abhyudaya College of Engineering & Research", "", "Maharashtra", "Hostel food quality", "12-10-2026",
     "PGRC", "Pending", "Food served in the hostel mess is of poor quality.", 4, "no", "", "", ""],
    ["IMP/PGRC/2026/007", "Navankur College of Engineering", "", "Maharashtra", "Fee fraud / excess fee", "02-09-2026", "PGRC",
     "Disposed", "Development charges collected without receipts.", 3, "yes", "", "", ""],
    ["IMP/PGRC/2026/001", "Sankalp Inst. of Engg. & Tech.", "", "Madhya Pradesh", "Fee refund", "21-10-2026", "PGRC", "Pending",
     "Same complaint number repeated in the register.", 1, "no", "", "", ""],
    ["IMP/RO/2026/009", "Navankur College of Engineering, Kolhapur", "", "Maharashtra", "Examination", "05-08-2026",
     "Regional Office", "Disposed", "Revaluation results delayed for two months.", 6, "no", "01-10-2026", "Not substantiated", ""],
    ["IMP/PGRC/2026/010", "", "", "Kerala", "General", "10-10-2026", "PGRC", "Pending", "Query about course recognition.", 1, "no",
     "", "", ""],
    ["IMP/AB/2026/011", "Abhyudaya College of Engineering & Research", "", "Maharashtra", "Approval", "01-10-2026", "Approval Bureau",
     "Under process", "Change of name application received; scrutiny pending.", 1, "no", "", "", ""],
    ["IMP/LC/2026/012", "Abhyudaya Engg College", "", "Maharashtra", "Withheld certificates", "14-10-2026", "Legal Cell", "Pending",
     "Original certificates withheld; complainant has approached the High Court.", 1, "yes", "", "", "Court"],
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "sample_institutions.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(INSTITUTION_ROWS)
    wb = xlsxwriter.Workbook(str(OUT / "sample_complaints.xlsx"))
    notes = wb.add_worksheet("Read me")
    notes.write(0, 0, "Synthetic sample register for the AgniDrishti import wizard. Rows 5, 6, 7, 8 and 10 of the register "
                      "are intentionally invalid.")
    ws = wb.add_worksheet("Complaints Register")
    bold = wb.add_format({"bold": True})
    for j, h in enumerate(COMPLAINT_HEADER):
        ws.write(0, j, h, bold)
    for i, row in enumerate(COMPLAINT_ROWS, start=1):
        for j, v in enumerate(row):
            ws.write(i, j, v)
    wb.close()
    print(f"wrote samples to {OUT}")


if __name__ == "__main__":
    main()
