-- SAMANVAY core schema. SQLite dialect, written to stay close to portable SQL.
-- Dates are ISO 'YYYY-MM-DD' text; timestamps are UTC ISO-8601 text ending in 'Z'.

CREATE TABLE id_counters (
  name  TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);

CREATE TABLE app_settings (
  key        TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  updated_by TEXT
);

CREATE TABLE seed_runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  seed              INTEGER NOT NULL,
  anchor_date       TEXT NOT NULL,
  generator_version TEXT NOT NULL,
  counts_json       TEXT NOT NULL,
  fingerprint       TEXT NOT NULL,
  created_at        TEXT NOT NULL
);

CREATE TABLE regions (
  code       TEXT PRIMARY KEY,
  name       TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE states (
  name        TEXT PRIMARY KEY,
  region_code TEXT NOT NULL REFERENCES regions(code)
);

CREATE TABLE bureaus (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL,
  description TEXT,
  sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE officers (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  designation  TEXT NOT NULL,
  bureau_code  TEXT NOT NULL REFERENCES bureaus(code),
  region_code  TEXT REFERENCES regions(code),
  active       INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX ix_officers_bureau ON officers(bureau_code);

CREATE TABLE demo_users (
  id           TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role         TEXT NOT NULL,
  bureau_code  TEXT REFERENCES bureaus(code),
  region_code  TEXT REFERENCES regions(code),
  officer_id   TEXT REFERENCES officers(id),
  description  TEXT,
  sort_order   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE trusts (
  id               TEXT PRIMARY KEY,
  name             TEXT NOT NULL,
  registration_ref TEXT,
  state            TEXT,
  provenance       TEXT NOT NULL,
  is_synthetic     INTEGER NOT NULL DEFAULT 1,
  notes            TEXT,
  created_at       TEXT NOT NULL
);

CREATE TABLE institutions (
  id                    TEXT PRIMARY KEY,
  permanent_id          TEXT UNIQUE,
  name                  TEXT NOT NULL,
  name_norm             TEXT NOT NULL,
  institution_type      TEXT,
  address_line          TEXT,
  city                  TEXT,
  district              TEXT,
  state                 TEXT NOT NULL REFERENCES states(name),
  region_code           TEXT NOT NULL REFERENCES regions(code),
  pincode               TEXT,
  established_year      INTEGER,
  intake_total          INTEGER,
  intake_source         TEXT,
  courses_json          TEXT NOT NULL DEFAULT '[]',
  trust_id              TEXT REFERENCES trusts(id),
  trust_relation_source TEXT,
  status                TEXT NOT NULL DEFAULT 'ACTIVE',
  is_synthetic          INTEGER NOT NULL DEFAULT 1,
  provenance_json       TEXT NOT NULL DEFAULT '{}',
  demo_tag              TEXT,
  created_at            TEXT NOT NULL,
  updated_at            TEXT NOT NULL
);
CREATE INDEX ix_inst_region ON institutions(region_code);
CREATE INDEX ix_inst_state ON institutions(state);
CREATE INDEX ix_inst_trust ON institutions(trust_id);
CREATE INDEX ix_inst_name_norm ON institutions(name_norm);

CREATE TABLE institution_aliases (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  institution_id TEXT NOT NULL REFERENCES institutions(id),
  alias          TEXT NOT NULL,
  alias_norm     TEXT NOT NULL,
  alias_type     TEXT NOT NULL,
  source         TEXT NOT NULL,
  created_by     TEXT,
  created_at     TEXT NOT NULL,
  UNIQUE (institution_id, alias_norm)
);
CREATE INDEX ix_alias_norm ON institution_aliases(alias_norm);

CREATE TABLE match_feedback (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_norm       TEXT NOT NULL,
  institution_id TEXT NOT NULL REFERENCES institutions(id),
  decision       TEXT NOT NULL,
  review_id      TEXT,
  decided_by     TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX ix_feedback_raw ON match_feedback(raw_norm, institution_id);

CREATE TABLE category_rules (
  code            TEXT PRIMARY KEY,
  label           TEXT NOT NULL,
  description     TEXT,
  family          TEXT NOT NULL,
  severity_level  INTEGER NOT NULL,
  severity_weight REAL NOT NULL,
  sla_days        INTEGER NOT NULL,
  default_bureau  TEXT NOT NULL REFERENCES bureaus(code),
  keywords_json   TEXT NOT NULL DEFAULT '[]',
  active          INTEGER NOT NULL DEFAULT 1,
  sort_order      INTEGER NOT NULL DEFAULT 0,
  updated_at      TEXT NOT NULL,
  updated_by      TEXT
);

CREATE TABLE master_cases (
  id               TEXT PRIMARY KEY,
  kind             TEXT NOT NULL DEFAULT 'DUPLICATE_MERGE',
  institution_id   TEXT NOT NULL REFERENCES institutions(id),
  title            TEXT NOT NULL,
  lead_bureau_code TEXT REFERENCES bureaus(code),
  status           TEXT NOT NULL,
  overlap_alert_id TEXT,
  created_by       TEXT,
  created_role     TEXT,
  created_at       TEXT NOT NULL,
  dissolved_by     TEXT,
  dissolved_at     TEXT,
  remarks          TEXT
);

CREATE TABLE complaints (
  id                       TEXT PRIMARY KEY,
  source_system            TEXT NOT NULL,
  source_ref               TEXT,
  external_ref             TEXT,
  channel                  TEXT NOT NULL,
  institution_id           TEXT REFERENCES institutions(id),
  institution_name_raw     TEXT NOT NULL,
  institution_address_raw  TEXT,
  institution_pincode_raw  TEXT,
  permanent_id_raw         TEXT,
  match_status             TEXT NOT NULL,
  match_confidence         REAL,
  category_code            TEXT NOT NULL REFERENCES category_rules(code),
  subject                  TEXT NOT NULL,
  description              TEXT NOT NULL,
  received_date            TEXT NOT NULL,
  bureau_code              TEXT NOT NULL REFERENCES bureaus(code),
  origin_bureau_code       TEXT NOT NULL REFERENCES bureaus(code),
  assigned_officer_id      TEXT REFERENCES officers(id),
  status                   TEXT NOT NULL,
  escalation_level         INTEGER NOT NULL DEFAULT 0,
  transfer_count           INTEGER NOT NULL DEFAULT 0,
  complainant_count        INTEGER NOT NULL DEFAULT 1,
  complainant_type         TEXT NOT NULL DEFAULT 'STUDENT',
  evidence_count           INTEGER NOT NULL DEFAULT 0,
  evidence_note            TEXT,
  reference_flag           TEXT NOT NULL DEFAULT 'NONE',
  reference_note           TEXT,
  sla_days                 INTEGER NOT NULL,
  expected_disposal_date   TEXT NOT NULL,
  disposed_date            TEXT,
  outcome                  TEXT,
  outcome_remarks          TEXT,
  last_action_type         TEXT,
  last_action_at           TEXT,
  last_action_summary      TEXT,
  next_action              TEXT,
  next_action_due          TEXT,
  priority_score           REAL,
  priority_band            TEXT,
  priority_computed_at     TEXT,
  priority_override_band   TEXT,
  priority_override_reason TEXT,
  ml_category              TEXT,
  ml_confidence            REAL,
  master_case_id           TEXT REFERENCES master_cases(id),
  region_code              TEXT REFERENCES regions(code),
  state                    TEXT,
  is_synthetic             INTEGER NOT NULL DEFAULT 1,
  demo_tag                 TEXT,
  created_at               TEXT NOT NULL,
  updated_at               TEXT NOT NULL,
  created_by               TEXT
);
CREATE INDEX ix_cmp_inst ON complaints(institution_id);
CREATE INDEX ix_cmp_bureau_status ON complaints(bureau_code, status);
CREATE INDEX ix_cmp_status ON complaints(status);
CREATE INDEX ix_cmp_category ON complaints(category_code);
CREATE INDEX ix_cmp_received ON complaints(received_date);
CREATE INDEX ix_cmp_region ON complaints(region_code);
CREATE INDEX ix_cmp_master ON complaints(master_case_id);
CREATE INDEX ix_cmp_source_ref ON complaints(source_ref);
CREATE INDEX ix_cmp_external_ref ON complaints(external_ref);
CREATE INDEX ix_cmp_due ON complaints(expected_disposal_date);

CREATE TABLE master_case_members (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  master_case_id TEXT NOT NULL REFERENCES master_cases(id),
  case_id        TEXT NOT NULL REFERENCES complaints(id),
  added_by       TEXT,
  added_at       TEXT NOT NULL,
  removed_by     TEXT,
  removed_at     TEXT,
  remarks        TEXT
);
CREATE INDEX ix_mcm_master ON master_case_members(master_case_id);
CREATE INDEX ix_mcm_case ON master_case_members(case_id);

CREATE TABLE case_actions (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id         TEXT NOT NULL REFERENCES complaints(id),
  action_type     TEXT NOT NULL,
  action_at       TEXT NOT NULL,
  actor_id        TEXT,
  actor_label     TEXT NOT NULL,
  actor_role      TEXT,
  bureau_code     TEXT,
  officer_id      TEXT,
  remarks         TEXT,
  from_value      TEXT,
  to_value        TEXT,
  next_action     TEXT,
  next_action_due TEXT,
  doc_ids_json    TEXT NOT NULL DEFAULT '[]',
  is_synthetic    INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL
);
CREATE INDEX ix_act_case ON case_actions(case_id, action_at);
CREATE INDEX ix_act_type ON case_actions(action_type);

CREATE TABLE case_documents (
  id           TEXT PRIMARY KEY,
  case_id      TEXT NOT NULL REFERENCES complaints(id),
  doc_type     TEXT NOT NULL,
  title        TEXT NOT NULL,
  reference_no TEXT,
  file_name    TEXT,
  stored_name  TEXT,
  mime_type    TEXT,
  size_bytes   INTEGER,
  sha256       TEXT,
  added_by     TEXT,
  added_role   TEXT,
  is_synthetic INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL
);
CREATE INDEX ix_doc_case ON case_documents(case_id);

CREATE TABLE match_reviews (
  id                     TEXT PRIMARY KEY,
  raw_name               TEXT NOT NULL,
  raw_norm               TEXT NOT NULL,
  raw_address            TEXT,
  raw_pincode            TEXT,
  raw_state              TEXT,
  raw_permanent_id       TEXT,
  source_type            TEXT NOT NULL,
  source_ref             TEXT,
  best_institution_id    TEXT REFERENCES institutions(id),
  best_confidence        REAL,
  candidates_json        TEXT NOT NULL DEFAULT '[]',
  status                 TEXT NOT NULL,
  decided_institution_id TEXT REFERENCES institutions(id),
  decided_by             TEXT,
  decided_role           TEXT,
  decided_at             TEXT,
  remarks                TEXT,
  created_at             TEXT NOT NULL
);
CREATE INDEX ix_mr_status ON match_reviews(status);
CREATE INDEX ix_mr_source ON match_reviews(source_ref);

CREATE TABLE overlap_alerts (
  id                  TEXT PRIMARY KEY,
  institution_id      TEXT NOT NULL REFERENCES institutions(id),
  tier                TEXT NOT NULL,
  headline            TEXT NOT NULL,
  score               REAL NOT NULL,
  status              TEXT NOT NULL,
  trigger_type        TEXT NOT NULL,
  trigger_case_id     TEXT,
  trigger_action_id   INTEGER,
  cross_bureau        INTEGER NOT NULL DEFAULT 0,
  bureaus_json        TEXT NOT NULL DEFAULT '[]',
  rules_json          TEXT NOT NULL DEFAULT '[]',
  signals_json        TEXT NOT NULL DEFAULT '{}',
  recommended_lead    TEXT,
  recommendation_json TEXT,
  next_step           TEXT,
  lead_decision       TEXT,
  decided_lead        TEXT,
  decision_remarks    TEXT,
  decided_by          TEXT,
  decided_role        TEXT,
  decided_at          TEXT,
  status_remarks      TEXT,
  status_by           TEXT,
  status_at           TEXT,
  pair_keys_json      TEXT NOT NULL DEFAULT '[]',
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL
);
CREATE INDEX ix_ovl_inst ON overlap_alerts(institution_id);
CREATE INDEX ix_ovl_status ON overlap_alerts(status, tier);

CREATE TABLE overlap_alert_cases (
  alert_id TEXT NOT NULL REFERENCES overlap_alerts(id),
  case_id  TEXT NOT NULL REFERENCES complaints(id),
  role     TEXT NOT NULL,
  PRIMARY KEY (alert_id, case_id)
);
CREATE INDEX ix_ovc_case ON overlap_alert_cases(case_id);

CREATE TABLE case_links (
  id               TEXT PRIMARY KEY,
  case_a           TEXT NOT NULL REFERENCES complaints(id),
  case_b           TEXT NOT NULL REFERENCES complaints(id),
  link_type        TEXT NOT NULL,
  overlap_alert_id TEXT REFERENCES overlap_alerts(id),
  active           INTEGER NOT NULL DEFAULT 1,
  remarks          TEXT,
  created_by       TEXT,
  created_role     TEXT,
  created_at       TEXT NOT NULL,
  removed_by       TEXT,
  removed_at       TEXT,
  removed_remarks  TEXT
);
CREATE UNIQUE INDEX ux_link_active ON case_links(case_a, case_b, link_type) WHERE active = 1;
CREATE INDEX ix_link_b ON case_links(case_b);

CREATE TABLE priority_overrides (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  case_id        TEXT NOT NULL REFERENCES complaints(id),
  previous_band  TEXT,
  previous_score REAL,
  new_band       TEXT,
  reason         TEXT NOT NULL,
  actor_id       TEXT,
  actor_role     TEXT,
  bureau_code    TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX ix_po_case ON priority_overrides(case_id);

CREATE TABLE alerts (
  id               TEXT PRIMARY KEY,
  alert_type       TEXT NOT NULL,
  severity         TEXT NOT NULL,
  title            TEXT NOT NULL,
  message          TEXT NOT NULL,
  institution_id   TEXT REFERENCES institutions(id),
  case_id          TEXT REFERENCES complaints(id),
  overlap_alert_id TEXT REFERENCES overlap_alerts(id),
  target_bureau    TEXT,
  target_region    TEXT,
  state            TEXT NOT NULL,
  dedupe_key       TEXT NOT NULL UNIQUE,
  channel          TEXT NOT NULL DEFAULT 'IN_APP',
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  acted_by         TEXT,
  acted_role       TEXT,
  acted_at         TEXT,
  action_remarks   TEXT
);
CREATE INDEX ix_alert_state ON alerts(state, severity);
CREATE INDEX ix_alert_case ON alerts(case_id);
CREATE INDEX ix_alert_type ON alerts(alert_type);

CREATE TABLE audit_events (
  seq          INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id     TEXT NOT NULL UNIQUE,
  ts           TEXT NOT NULL,
  actor_id     TEXT,
  actor_label  TEXT,
  actor_role   TEXT,
  actor_bureau TEXT,
  action       TEXT NOT NULL,
  entity_type  TEXT NOT NULL,
  entity_id    TEXT,
  before_json  TEXT,
  after_json   TEXT,
  remarks      TEXT,
  payload_hash TEXT NOT NULL,
  prev_hash    TEXT NOT NULL,
  hash         TEXT NOT NULL
);
CREATE INDEX ix_audit_ts ON audit_events(ts);
CREATE INDEX ix_audit_action ON audit_events(action);
CREATE INDEX ix_audit_entity ON audit_events(entity_id);

CREATE TABLE public_signals (
  id                   TEXT PRIMARY KEY,
  signal_type          TEXT NOT NULL,
  verification         TEXT NOT NULL,
  scope                TEXT NOT NULL,
  title                TEXT NOT NULL,
  publisher            TEXT,
  source_url           TEXT,
  published_date       TEXT,
  retrieved_at         TEXT,
  summary              TEXT NOT NULL,
  raw_institution_text TEXT,
  institution_id       TEXT REFERENCES institutions(id),
  match_confidence     REAL,
  match_status         TEXT NOT NULL,
  notes                TEXT,
  import_job_id        TEXT,
  created_at           TEXT NOT NULL
);

CREATE TABLE import_jobs (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  status          TEXT NOT NULL,
  file_name       TEXT NOT NULL,
  file_type       TEXT NOT NULL,
  stored_name     TEXT NOT NULL,
  file_sha256     TEXT NOT NULL,
  size_bytes      INTEGER NOT NULL,
  sheets_json     TEXT NOT NULL DEFAULT '[]',
  sheet_name      TEXT,
  columns_json    TEXT NOT NULL DEFAULT '[]',
  row_count       INTEGER NOT NULL DEFAULT 0,
  mapping_json    TEXT,
  mapping_hash    TEXT,
  validation_json TEXT,
  summary_json    TEXT,
  policy          TEXT NOT NULL DEFAULT 'SKIP_INVALID_ROWS',
  uploaded_by     TEXT,
  uploaded_role   TEXT,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  validated_at    TEXT,
  committed_at    TEXT
);

CREATE TABLE import_row_issues (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id     TEXT NOT NULL REFERENCES import_jobs(id),
  row_number INTEGER NOT NULL,
  field      TEXT,
  severity   TEXT NOT NULL,
  code       TEXT NOT NULL,
  message    TEXT NOT NULL,
  value      TEXT
);
CREATE INDEX ix_iri_job ON import_row_issues(job_id, row_number);
