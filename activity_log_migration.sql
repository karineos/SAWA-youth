-- Adds the Activity Log: a "who changed what, when" audit trail across
-- the app, visible to Owners. The table is brand new, so this is safe to
-- run anytime.

CREATE TABLE IF NOT EXISTS activity_log (
    id SERIAL PRIMARY KEY,
    admin_id INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    admin_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    entity_label TEXT,
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
