-- Adds extended profile fields to the members table.
-- Run this once in the Supabase SQL Editor if your database was created
-- before these fields were added to schema.sql.

ALTER TABLE members ADD COLUMN IF NOT EXISTS skills TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS interests TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS motivation TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS date_joined TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS blood_type TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS learn_more TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS has_transportation TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT;
ALTER TABLE members ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT;
