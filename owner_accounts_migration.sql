-- Creates two Owner accounts: Karine Osman and Rami Khalil.
-- Run this once in the Supabase SQL Editor, AFTER deploying the code that
-- adds the 'owner' role (owners can manage admin accounts; regular admins
-- cannot). If a username already exists, this updates it in place instead
-- of failing, so it's safe to run even if one of these accounts was
-- created earlier under the 'admin' role.
--
-- The password hashes below were generated locally with the same
-- pbkdf2:sha256 method the app already uses — no plaintext password is
-- stored here or was ever sent to this database directly. Temporary
-- login credentials are in the chat response that included this file;
-- both people should log in and change their password immediately
-- (there's no in-app "change my own password" page yet, so for now that
-- means an Owner using Admins > Edit on their own account, or on each
-- other's).

INSERT INTO admins (username, password_hash, full_name, role)
VALUES ('karine', 'pbkdf2:sha256:600000$y24mIQYt1CrLGvkb$df791c218b96f045a96080dcb3797b5b018969766bc683ca677aacccb921c67c', 'Karine Osman', 'owner')
ON CONFLICT (username) DO UPDATE SET
    password_hash = EXCLUDED.password_hash,
    full_name = EXCLUDED.full_name,
    role = 'owner';

INSERT INTO admins (username, password_hash, full_name, role)
VALUES ('rami', 'pbkdf2:sha256:600000$kmHFvoDAsC6T8gGT$c97b6135b99c63fc3f128f646868fc3264f410ce77f5bfd5557de532ad3b25f9', 'Rami Khalil', 'owner')
ON CONFLICT (username) DO UPDATE SET
    password_hash = EXCLUDED.password_hash,
    full_name = EXCLUDED.full_name,
    role = 'owner';
