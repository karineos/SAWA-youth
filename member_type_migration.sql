-- Distinguishes real Members from one-off event Guests, so a public sign-up
-- from someone who never comes back doesn't clutter the curated Members list.
-- Run this once in the Supabase SQL Editor. Safe to run anytime (existing
-- members all default to 'member', nothing changes for them).

ALTER TABLE members ADD COLUMN IF NOT EXISTS member_type TEXT DEFAULT 'member';
UPDATE members SET member_type = 'member' WHERE member_type IS NULL;
