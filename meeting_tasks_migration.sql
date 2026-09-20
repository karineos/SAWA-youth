-- Adds action items (tasks) to meetings: each has an owner, a due date, and
-- a done / not done status. The table is brand new, so this is safe to run
-- anytime.

CREATE TABLE IF NOT EXISTS meeting_tasks (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    owner_name TEXT,
    due_date TEXT,
    is_done INTEGER NOT NULL DEFAULT 0,
    completed_at TIMESTAMP,
    created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
