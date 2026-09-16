-- Adds custom questions tied to an EVENT that people answer after filling out
-- a public sign-up form for that event. Safe to run even if you already ran an
-- earlier version of this file (drops and recreates the two tables it touches;
-- both are brand new so there's no real data to lose).

DROP TABLE IF EXISTS signup_question_answers;
DROP TABLE IF EXISTS signup_questions;

ALTER TABLE signup_responses ADD COLUMN IF NOT EXISTS token TEXT UNIQUE;

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
