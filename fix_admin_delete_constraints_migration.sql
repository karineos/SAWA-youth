-- Fixes a bug: deleting an admin who had created a meeting, added meeting
-- minutes, or recorded a business assessment crashed with an Internal
-- Server Error, because those tables' created_by/assessed_by columns
-- pointed at admins(id) with no ON DELETE behavior (Postgres's default is
-- to block the delete entirely).
--
-- This changes it to ON DELETE SET NULL: deleting an admin now keeps their
-- meetings/minutes/assessments intact, just with the "created by" left
-- blank (shown as "Unknown" in the app) instead of blocking the delete.
--
-- Run this once in the Supabase SQL Editor. Safe to run anytime.

ALTER TABLE meetings DROP CONSTRAINT IF EXISTS meetings_created_by_fkey;
ALTER TABLE meetings ADD CONSTRAINT meetings_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES admins(id) ON DELETE SET NULL;

ALTER TABLE meeting_minutes DROP CONSTRAINT IF EXISTS meeting_minutes_created_by_fkey;
ALTER TABLE meeting_minutes ADD CONSTRAINT meeting_minutes_created_by_fkey
    FOREIGN KEY (created_by) REFERENCES admins(id) ON DELETE SET NULL;

ALTER TABLE business_assessments DROP CONSTRAINT IF EXISTS business_assessments_assessed_by_fkey;
ALTER TABLE business_assessments ADD CONSTRAINT business_assessments_assessed_by_fkey
    FOREIGN KEY (assessed_by) REFERENCES admins(id) ON DELETE SET NULL;
