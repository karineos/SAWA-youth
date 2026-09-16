-- Adds public workshop sign-up forms and their responses.
-- Run this once in the Supabase SQL Editor to enable the Sign-Up Forms feature.
-- Both tables are brand new, so this is safe to run anytime.

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
    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
