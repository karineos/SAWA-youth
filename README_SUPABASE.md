# Sawa Youth CRM — Supabase Deployment

## 1. Add environment variables on Vercel

In Vercel → Project → Settings → Environment Variables:

- `DATABASE_URL` = your Supabase transaction pooler connection string
- `SECRET_KEY` = a long random secret

Generate secret:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## 2. Install requirements locally

```bash
pip install -r requirements.txt
```

## 3. Migrate your private local SQLite data to Supabase

Keep `data/crm.sqlite` local/private. Do not commit it to GitHub.

Run:

```bash
export DATABASE_URL="your_supabase_connection_string"
python migrate_to_supabase.py
```

## 4. Push code to GitHub

Make sure `.gitignore` contains:

```text
data/crm.sqlite
*.sqlite
*.db
venv/
__pycache__/
```

Then:

```bash
git add .
git commit -m "Convert CRM to Supabase PostgreSQL"
git push
```

## 5. Redeploy Vercel

Vercel will use Supabase for the database.

Default admin, if no admins exist:
- username: `admin`
- password: `ChangeMe123!`

Change it immediately.