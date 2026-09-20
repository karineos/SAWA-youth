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
    skills TEXT,
    interests TEXT,
    motivation TEXT,
    date_joined TEXT,
    blood_type TEXT,
    learn_more TEXT,
    has_transportation TEXT,
    emergency_contact_name TEXT,
    emergency_contact_phone TEXT,
    member_type TEXT DEFAULT 'member',
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

CREATE TABLE IF NOT EXISTS signup_forms (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT,
    fields TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS signup_responses (
    id SERIAL PRIMARY KEY,
    signup_form_id INTEGER NOT NULL REFERENCES signup_forms(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    matched_existing INTEGER NOT NULL DEFAULT 0,
    token TEXT UNIQUE,
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS event_questions (
    id SERIAL PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    question_text TEXT NOT NULL,
    field_type TEXT DEFAULT 'text',
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS signup_question_answers (
    id SERIAL PRIMARY KEY,
    signup_response_id INTEGER NOT NULL REFERENCES signup_responses(id) ON DELETE CASCADE,
    event_question_id INTEGER NOT NULL REFERENCES event_questions(id) ON DELETE CASCADE,
    answer_text TEXT
);

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    department TEXT,
    meeting_date TEXT,
    meeting_time TEXT,
    location TEXT,
    notes TEXT,
    created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meeting_minutes (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS businesses (
    id SERIAL PRIMARY KEY,
    business_name TEXT NOT NULL,
    owner_name TEXT,
    phone TEXT,
    sector TEXT,
    location TEXT,
    date_opened TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS business_assessments (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    assessment_date TEXT,
    monthly_income TEXT,
    monthly_profit TEXT,
    monthly_expenses TEXT,
    employees_count TEXT,
    challenges TEXT,
    support_needed TEXT,
    notes TEXT,
    assessed_by INTEGER REFERENCES admins(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);