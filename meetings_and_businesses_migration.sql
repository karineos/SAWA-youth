-- Adds Meetings (with Minutes of Meeting) and the Small Business Assessment
-- section. Run this once in the Supabase SQL Editor. All four tables are
-- brand new, so this is safe to run anytime.
--
-- Note: admin roles ('admin' vs 'contributor') use the existing admins.role
-- column, already in place — no schema change needed for that part.

CREATE TABLE IF NOT EXISTS meetings (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    department TEXT,
    meeting_date TEXT,
    meeting_time TEXT,
    location TEXT,
    notes TEXT,
    created_by INTEGER REFERENCES admins(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meeting_minutes (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_by INTEGER REFERENCES admins(id),
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
    assessed_by INTEGER REFERENCES admins(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
