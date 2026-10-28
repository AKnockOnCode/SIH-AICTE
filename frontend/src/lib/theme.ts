// Colour semantics shared by charts and chips (hex values mirror the tokens in app.css).
export const C = {
  navy: "#1F3864",
  blue: "#0071C1",
  orange: "#F28C28",
  orangeStrong: "#C9690A",
  green: "#2E8B3E",
  red: "#D64545",
  slate: "#8A94A6",
  slateInk: "#4F5A6D",
  line: "#D9E2F0",
  muted: "#5B6578",
  ink: "#1E2533",
  tint: "#F3F6FB",
} as const;

/** Bureau identity colours, following the PPT: RB blue, PGRC orange, Regional Offices green, other cells slate. */
export const BUREAU_COLOR: Record<string, string> = {
  RB: C.blue,
  PGRC: C.orange,
  RO: C.green,
  AB: "#4A6A9C",
  SDC: C.slate,
  LC: "#5B6578",
};
export const bureauColor = (code: string | null | undefined) => (code && BUREAU_COLOR[code]) || C.slate;

export const BAND_COLOR: Record<string, string> = { CRITICAL: C.red, HIGH: C.orange, MEDIUM: C.blue, LOW: C.slate };
export const BAND_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];

export const TIER_COLOR: Record<string, string> = { DUPLICATE: C.green, RELATED: C.orange, CONFLICT: C.red };
export const TIER_LABEL: Record<string, string> = { DUPLICATE: "Duplicate", RELATED: "Related", CONFLICT: "Conflict" };

export const RISK_COLOR: Record<string, string> = { HIGH: C.red, ELEVATED: C.orange, NORMAL: C.green };

export const STATUS_COLOR: Record<string, string> = {
  RECEIVED: C.blue,
  PENDING: C.orange,
  UNDER_PROCESS: C.blue,
  TRANSFERRED: C.slate,
  ESCALATED: C.navy,
  DISPOSED: C.green,
};

export function severityColor(level: number): string {
  if (level >= 4) return C.red;
  if (level === 3) return C.orange;
  return C.blue;
}
