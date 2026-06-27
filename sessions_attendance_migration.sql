-- Event sessions and attendee tracking are supported by existing sessions and attendance tables.
-- Use this if your Supabase DB does not have sessions yet.

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    session_date TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS attendance (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    session_id INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'Present',
    notes TEXT,
    UNIQUE(member_id, event_id, session_id)
);