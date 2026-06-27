CREATE TABLE IF NOT EXISTS admins (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT,
    role TEXT DEFAULT 'admin',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
    id SERIAL PRIMARY KEY,
    full_name_en TEXT NOT NULL,
    full_name_ar TEXT,
    phone TEXT,
    email TEXT,
    birth_date TEXT,
    gender TEXT,
    city TEXT,
    current_status TEXT,
    studied_where TEXT,
    field_of_study TEXT,
    work TEXT,
    english_level TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE,
    name TEXT NOT NULL,
    event_date TEXT,
    location TEXT,
    event_type TEXT,
    notes TEXT
);

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

CREATE TABLE IF NOT EXISTS surveys (
    id SERIAL PRIMARY KEY,
    survey_name TEXT,
    timestamp TEXT,
    full_name TEXT,
    phone TEXT,
    birth_date TEXT,
    gender TEXT,
    city TEXT,
    current_status TEXT,
    university_school TEXT,
    field_work TEXT,
    english_level TEXT,
    interest_reason TEXT,
    attended_before TEXT,
    learn_most TEXT,
    heard_from TEXT,
    raw_answers TEXT
);

CREATE TABLE IF NOT EXISTS survey_forms (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    source_link TEXT,
    source_sheet_name TEXT,
    source_notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS survey_questions (
    id SERIAL PRIMARY KEY,
    survey_form_id INTEGER NOT NULL REFERENCES survey_forms(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    field_key TEXT NOT NULL,
    field_type TEXT DEFAULT 'text',
    sort_order INTEGER DEFAULT 0
);