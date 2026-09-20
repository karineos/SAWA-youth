import os
import json
import csv
import io
import re
import secrets
import calendar as calendar_module
from datetime import date, timedelta
from itertools import groupby
from urllib.parse import quote

from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import psycopg2
import psycopg2.extras
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path
import psycopg2
import psycopg2.extras
APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "crm.sqlite"
database_url = os.environ.get("DATABASE_URL")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")
# Templates use `{{ x.field if x else '' }}` in many places, which only guards
# against x being missing — when x exists but x.field is NULL in the database,
# Jinja renders the literal text "None". Finalize runs on every {{ }} output,
# so this fixes it everywhere at once instead of patching each template line.
app.jinja_env.finalize = lambda value: "" if value is None else value


def public_signup_url(slug):
    """Build the shareable sign-up link. Prefers PUBLIC_BASE_URL (set this on
    Vercel to your real domain) over url_for(_external=True), since Vercel's
    Python runtime doesn't always report the real host back to Flask —
    without it, generated links can show localhost even in production."""
    base_url = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    if base_url:
        return f"{base_url}{url_for('public_signup', slug=slug)}"
    return url_for("public_signup", slug=slug, _external=True)


app.jinja_env.globals["public_signup_url"] = public_signup_url


def whatsapp_share_url(text):
    return f"https://wa.me/?text={quote(text)}"


app.jinja_env.globals["whatsapp_share_url"] = whatsapp_share_url


def whatsapp_chat_url(phone):
    """Build a WhatsApp click-to-chat link from a member's phone number.

    Numbers in this CRM are entered in local Lebanese format (with or
    without a leading 0, e.g. "03123456" or "70123456") rather than with
    a country code, so WhatsApp's international format needs the leading
    0 stripped and 961 added — unless a country code is already present.
    """
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        return None
    if digits.startswith("00"):
        digits = digits[2:]
    if not digits.startswith("961"):
        digits = "961" + digits.lstrip("0")
    return f"https://wa.me/{digits}"


app.jinja_env.globals["whatsapp_chat_url"] = whatsapp_chat_url


def csv_response(filename, header, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    response = app.response_class(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response

MEMBER_FIELDS = [
    "full_name_en", "full_name_ar", "phone", "email", "birth_date", "gender", "city",
    "current_status", "studied_where", "field_of_study", "work", "english_level", "notes",
    "skills", "interests", "motivation", "date_joined", "blood_type", "learn_more",
    "has_transportation", "emergency_contact_name", "emergency_contact_phone", "member_type",
]

# Fields offered on public sign-up forms. "always" fields are shown on every
# sign-up form and can't be unchecked by the admin building the form. Phone is
# the primary way we identify a returning member; since not everyone in Lebanon
# has an email (and not everyone has a phone either), we always collect both
# and fall back to matching on email when phone isn't provided — the public
# form only requires that at least one of the two is filled in.
MEMBER_FIELD_META = [
    {"key": "full_name_en", "label": "Full Name (English)", "type": "text", "category": "Personal Information", "always": True},
    {"key": "phone", "label": "Phone", "type": "text", "category": "Personal Information", "always": True},
    {"key": "email", "label": "Email", "type": "email", "category": "Personal Information", "always": True},
    {"key": "full_name_ar", "label": "Full Name (Arabic)", "type": "text", "category": "Personal Information", "always": False},
    {"key": "birth_date", "label": "Birth Date", "type": "date", "category": "Personal Information", "always": False},
    {"key": "gender", "label": "Gender", "type": "select_gender", "category": "Personal Information", "always": False},
    {"key": "city", "label": "City / Area", "type": "text", "category": "Personal Information", "always": False},
    {"key": "current_status", "label": "Current Status", "type": "text", "category": "Personal Information", "always": False},
    {"key": "studied_where", "label": "Studied Where / University", "type": "text", "category": "Education & Work", "always": False},
    {"key": "field_of_study", "label": "Field of Study", "type": "text", "category": "Education & Work", "always": False},
    {"key": "work", "label": "Work", "type": "text", "category": "Education & Work", "always": False},
    {"key": "english_level", "label": "English Level", "type": "text", "category": "Education & Work", "always": False},
    {"key": "skills", "label": "Skills", "type": "textarea", "category": "Sawa Journey", "always": False},
    {"key": "interests", "label": "Interests", "type": "textarea", "category": "Sawa Journey", "always": False},
    {"key": "motivation", "label": "Motivation for Joining Sawa", "type": "textarea", "category": "Sawa Journey", "always": False},
    {"key": "learn_more", "label": "What Would You Like to Learn More?", "type": "textarea", "category": "Sawa Journey", "always": False},
    {"key": "blood_type", "label": "Blood Type", "type": "select_bloodtype", "category": "Safety & Emergency Contact", "always": False},
    {"key": "has_transportation", "label": "Access to Transportation", "type": "select_yesno", "category": "Safety & Emergency Contact", "always": False},
    {"key": "emergency_contact_name", "label": "Emergency Contact Name", "type": "text", "category": "Safety & Emergency Contact", "always": False},
    {"key": "emergency_contact_phone", "label": "Emergency Contact Phone", "type": "text", "category": "Safety & Emergency Contact", "always": False},
]
ALWAYS_FIELD_KEYS = [f["key"] for f in MEMBER_FIELD_META if f["always"]]
OPTIONAL_FIELD_META = [f for f in MEMBER_FIELD_META if not f["always"]]
OPTIONAL_FIELD_KEYS = [f["key"] for f in OPTIONAL_FIELD_META]
OPTIONAL_FIELD_CATEGORIES = [(cat, list(items)) for cat, items in groupby(OPTIONAL_FIELD_META, key=lambda f: f["category"])]

GENDER_OPTIONS = ["Male", "Female"]
BLOOD_TYPE_OPTIONS = ["O+", "O-", "A+", "A-", "B+", "B-", "AB+", "AB-"]
app.jinja_env.globals["GENDER_OPTIONS"] = GENDER_OPTIONS
app.jinja_env.globals["BLOOD_TYPE_OPTIONS"] = BLOOD_TYPE_OPTIONS


def fields_by_category(fields):
    return [(cat, list(items)) for cat, items in groupby(fields, key=lambda f: f["category"])]


def generate_unique_slug(conn):
    while True:
        slug = secrets.token_urlsafe(6)
        if not conn.execute("SELECT id FROM signup_forms WHERE slug=?", (slug,)).fetchone():
            return slug


def generate_unique_response_token(conn):
    while True:
        token = secrets.token_urlsafe(12)
        if not conn.execute("SELECT id FROM signup_responses WHERE token=?", (token,)).fetchone():
            return token


class DbWrapper:
    def __init__(self, conn, is_postgres=False):
        self.conn = conn
        self.is_postgres = is_postgres

    def _sql(self, sql):
        if self.is_postgres:
            sql = sql.replace("?", "%s")
            sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
            if "INSERT OR IGNORE" in sql:
                sql = sql.replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
            sql = sql.replace(
                "GROUP_CONCAT(DISTINCT e.name)",
                "STRING_AGG(DISTINCT e.name, ', ')"
            )
            sql = sql.replace(
                "GROUP_CONCAT(COALESCE(s.name, 'Full event'), ', ')",
                "STRING_AGG(COALESCE(s.name, 'Full event'), ', ')"
            )
        return sql

    def execute(self, sql, params=()):
        cur = self.conn.cursor()
        try:
            cur.execute(self._sql(sql), params)
        except Exception:
            self.conn.rollback()
            raise
        return cur

    def executescript(self, script):
        cur = self.conn.cursor()
        cur.execute(script)
        return cur

    def commit(self):
        return self.conn.commit()

    def close(self):
        return self.conn.close()


def get_db():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        conn = psycopg2.connect(
            database_url,
            cursor_factory=psycopg2.extras.RealDictCursor
        )
        return DbWrapper(conn, True)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return DbWrapper(conn, False)

def init_local_schema():
    """Bootstrap members/events/sessions/etc. tables for local SQLite dev.
    On Postgres (DATABASE_URL set), these tables already exist in Supabase
    and this is a no-op — never runs DDL against the production database."""
    conn = get_db()
    if conn.is_postgres:
        conn.close()
        return
    sql_text = (APP_DIR / "schema.sql").read_text(encoding="utf-8")
    sql_text = sql_text.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    for statement in sql_text.split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)

    existing_columns = {row["name"] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
    for column in ["skills", "interests", "motivation", "date_joined", "blood_type",
                   "learn_more", "has_transportation", "emergency_contact_name", "emergency_contact_phone",
                   "member_type"]:
        if column not in existing_columns:
            default = " DEFAULT 'member'" if column == "member_type" else ""
            conn.execute(f"ALTER TABLE members ADD COLUMN {column} TEXT{default}")

    existing_response_columns = {row["name"] for row in conn.execute("PRAGMA table_info(signup_responses)").fetchall()}
    if "token" not in existing_response_columns:
        conn.execute("ALTER TABLE signup_responses ADD COLUMN token TEXT")

    conn.commit()
    conn.close()


def init_admins():
    conn = get_db()
    id_column = "id SERIAL PRIMARY KEY" if conn.is_postgres else "id INTEGER PRIMARY KEY AUTOINCREMENT"
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS admins (
            {id_column},
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT,
            role TEXT DEFAULT 'admin',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    existing = conn.execute("SELECT COUNT(*) AS c FROM admins").fetchone()["c"]
    if existing == 0:
        conn.execute(
            "INSERT INTO admins(username, password_hash, full_name, role) VALUES (?, ?, ?, ?) RETURNING id",
            ("admin", generate_password_hash("ChangeMe123!", method="pbkdf2:sha256"), "Main Admin", "admin")
        )
        conn.commit()
    conn.close()


def get_new_id(cur):
    if cur.description:
        row = cur.fetchone()
        if row:
            return row.get("id") if isinstance(row, dict) else row[0]
    return cur.lastrowid


def member_field_value(data, key):
    value = data.get(key, "").strip()
    if key == "member_type" and not value:
        return "member"
    return value


def add_attendance(conn, member_id, event_id, session_id=None, status="Present"):
    """Record attendance without creating duplicates.

    UNIQUE(member_id, event_id, session_id) only stops duplicates for a specific
    session — for "full event" attendance session_id is NULL, and SQL treats
    NULL != NULL, so the constraint never matches and INSERT OR IGNORE silently
    lets duplicates through. Full-event attendance needs an explicit check instead.
    """
    if session_id:
        conn.execute(
            "INSERT OR IGNORE INTO attendance(member_id, event_id, session_id, status) VALUES (?, ?, ?, ?)",
            (member_id, event_id, session_id, status)
        )
    else:
        existing = conn.execute(
            "SELECT id FROM attendance WHERE member_id=? AND event_id=? AND session_id IS NULL",
            (member_id, event_id)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO attendance(member_id, event_id, session_id, status) VALUES (?, ?, NULL, ?)",
                (member_id, event_id, status)
            )


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


def admin_required(view):
    """Like login_required, but also requires the 'admin' or 'owner' role —
    Contributors are limited to taking attendance and adding meeting
    minutes, so anything that manages members, events, forms, meetings, or
    businesses needs this instead of plain login_required. Owners can do
    everything an admin can, plus manage admin accounts (see owner_required)."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        if session.get("admin_role") not in ("admin", "owner"):
            flash("Only admins can do that.")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped_view


def owner_required(view):
    """Only Owners can manage admin accounts — regular Admins cannot add,
    edit, or remove other admins/owners."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        if session.get("admin_role") != "owner":
            flash("Only owners can manage admin accounts.")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped_view


_schema_ready = False


def ensure_schema_ready():
    """Run schema/admin setup once per running process instead of on every
    /login request — CREATE TABLE IF NOT EXISTS and reading schema.sql from
    disk is wasted work once the tables already exist."""
    global _schema_ready
    if not _schema_ready:
        init_local_schema()
        init_admins()
        _schema_ready = True


@app.route("/login", methods=["GET", "POST"])
def login():
    ensure_schema_ready()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_db()
        admin = conn.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
        conn.close()
        if admin and check_password_hash(admin["password_hash"], password):
            session["admin_id"] = admin["id"]
            session["admin_username"] = admin["username"]
            session["admin_name"] = admin["full_name"] or admin["username"]
            session["admin_role"] = admin["role"] or "admin"
            flash("Logged in successfully.")
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.")
    return redirect(url_for("login"))

@app.route("/admins", methods=["GET", "POST"])
@owner_required
def admins():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "admin").strip()
        role = role if role in ("owner", "admin", "contributor") else "admin"
        if not username or not password:
            flash("Username and password are required.")
        else:
            try:
                conn.execute(
                    "INSERT INTO admins(username, password_hash, full_name, role) VALUES (?, ?, ?, ?) RETURNING id",
                    (username, generate_password_hash(password, method="pbkdf2:sha256"), full_name, role)
                )
                conn.commit()
                flash("Admin added successfully.")
            except (sqlite3.IntegrityError, psycopg2.IntegrityError):
                flash("This username already exists.")
    rows = conn.execute("SELECT id, username, full_name, role, created_at FROM admins ORDER BY username").fetchall()
    conn.close()
    return render_template("admins.html", admins=rows)

@app.route("/admins/<int:admin_id>/edit", methods=["GET", "POST"])
@owner_required
def admin_edit(admin_id):
    conn = get_db()
    admin = conn.execute("SELECT id, username, full_name, role FROM admins WHERE id=?", (admin_id,)).fetchone()
    if not admin:
        conn.close()
        flash("Admin not found.")
        return redirect(url_for("admins"))
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "admin").strip()
        role = role if role in ("owner", "admin", "contributor") else "admin"
        password = request.form.get("password", "")
        if admin_id == session.get("admin_id") and role != "owner":
            conn.close()
            flash("You cannot remove your own owner access while logged in.")
            return redirect(url_for("admins"))
        if password:
            conn.execute(
                "UPDATE admins SET full_name=?, role=?, password_hash=? WHERE id=?",
                (full_name, role, generate_password_hash(password, method="pbkdf2:sha256"), admin_id)
            )
        else:
            conn.execute("UPDATE admins SET full_name=?, role=? WHERE id=?", (full_name, role, admin_id))
        conn.commit()
        conn.close()
        if admin_id == session.get("admin_id"):
            session["admin_role"] = role
            session["admin_name"] = full_name or admin["username"]
        flash("Admin updated successfully.")
        return redirect(url_for("admins"))
    conn.close()
    return render_template("admin_form.html", admin=admin)


@app.route("/admins/<int:admin_id>/delete", methods=["POST"])
@owner_required
def admin_delete(admin_id):
    if admin_id == session.get("admin_id"):
        flash("You cannot delete your own admin account while logged in.")
        return redirect(url_for("admins"))
    conn = get_db()
    try:
        conn.execute("DELETE FROM admins WHERE id=?", (admin_id,))
        conn.commit()
        flash("Admin deleted successfully.")
    except (sqlite3.IntegrityError, psycopg2.IntegrityError):
        flash("Couldn't delete this admin yet — a database update needs to run first (fix_admin_delete_constraints_migration.sql). Ask whoever manages the database to run it, then try again.")
    finally:
        conn.close()
    return redirect(url_for("admins"))

MEETING_DEPARTMENTS = ["Technology & Tamkeen", "Sawa Youth", "Ghassan Jisr Community", "SAWA"]


def known_departments(conn):
    used = {
        r["department"] for r in conn.execute(
            "SELECT DISTINCT department FROM meetings WHERE department IS NOT NULL AND department <> ''"
        ).fetchall()
    }
    return sorted(used | set(MEETING_DEPARTMENTS))


@app.route("/meetings")
@login_required
def meetings():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE title LIKE ? OR department LIKE ? OR location LIKE ?"
        params = [f"%{q}%"] * 3
    rows = conn.execute(f"""
        SELECT m.*, COUNT(mm.id) minutes_count
        FROM meetings m
        LEFT JOIN meeting_minutes mm ON mm.meeting_id = m.id
        {where}
        GROUP BY m.id
        ORDER BY m.meeting_date DESC, m.meeting_time DESC
    """, params).fetchall()
    conn.close()
    return render_template("meetings.html", meetings=rows, q=q)


@app.route("/meetings/new", methods=["GET", "POST"])
@admin_required
def meeting_new():
    conn = get_db()
    departments = known_departments(conn)
    if request.method == "POST":
        data = request.form
        title = data.get("title", "").strip()
        if not title:
            conn.close()
            flash("Meeting title is required.")
            return render_template("meeting_form.html", meeting=None, departments=departments)
        conn.execute(
            "INSERT INTO meetings(title, department, meeting_date, meeting_time, location, notes, created_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (title, data.get("department", "").strip(), data.get("meeting_date"), data.get("meeting_time"),
             data.get("location", "").strip(), data.get("notes", "").strip(), session.get("admin_id"))
        )
        conn.commit()
        conn.close()
        flash("Meeting scheduled successfully.")
        return redirect(url_for("meetings"))
    conn.close()
    return render_template("meeting_form.html", meeting=None, departments=departments)


@app.route("/meetings/<int:meeting_id>/edit", methods=["GET", "POST"])
@admin_required
def meeting_edit(meeting_id):
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        conn.close()
        flash("Meeting not found.")
        return redirect(url_for("meetings"))
    departments = known_departments(conn)
    if request.method == "POST":
        data = request.form
        title = data.get("title", "").strip()
        if not title:
            conn.close()
            flash("Meeting title is required.")
            return render_template("meeting_form.html", meeting=meeting, departments=departments)
        conn.execute(
            "UPDATE meetings SET title=?, department=?, meeting_date=?, meeting_time=?, location=?, notes=? WHERE id=?",
            (title, data.get("department", "").strip(), data.get("meeting_date"), data.get("meeting_time"),
             data.get("location", "").strip(), data.get("notes", "").strip(), meeting_id)
        )
        conn.commit()
        conn.close()
        flash("Meeting updated successfully.")
        return redirect(url_for("meetings"))
    conn.close()
    return render_template("meeting_form.html", meeting=meeting, departments=departments)


@app.route("/meetings/<int:meeting_id>/delete", methods=["POST"])
@admin_required
def meeting_delete(meeting_id):
    conn = get_db()
    conn.execute("DELETE FROM meetings WHERE id=?", (meeting_id,))
    conn.commit()
    conn.close()
    flash("Meeting deleted successfully.")
    return redirect(url_for("meetings"))


@app.route("/meetings/<int:meeting_id>")
@login_required
def meeting_detail(meeting_id):
    conn = get_db()
    meeting = conn.execute("SELECT * FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        conn.close()
        flash("Meeting not found.")
        return redirect(url_for("meetings"))
    minutes = conn.execute("""
        SELECT mm.*, COALESCE(a.full_name, a.username) AS author_name
        FROM meeting_minutes mm
        LEFT JOIN admins a ON a.id = mm.created_by
        WHERE mm.meeting_id = ?
        ORDER BY mm.created_at DESC
    """, (meeting_id,)).fetchall()
    conn.close()
    return render_template("meeting_detail.html", meeting=meeting, minutes=minutes)


@app.route("/meetings/<int:meeting_id>/minutes", methods=["POST"])
@login_required
def meeting_add_minutes(meeting_id):
    content = request.form.get("content", "").strip()
    conn = get_db()
    meeting = conn.execute("SELECT id FROM meetings WHERE id=?", (meeting_id,)).fetchone()
    if not meeting:
        conn.close()
        flash("Meeting not found.")
        return redirect(url_for("meetings"))
    if not content:
        conn.close()
        flash("Minutes can't be empty.")
        return redirect(url_for("meeting_detail", meeting_id=meeting_id))
    conn.execute(
        "INSERT INTO meeting_minutes(meeting_id, content, created_by) VALUES (?, ?, ?)",
        (meeting_id, content, session.get("admin_id"))
    )
    conn.commit()
    conn.close()
    flash("Minutes added successfully.")
    return redirect(url_for("meeting_detail", meeting_id=meeting_id))


@app.route("/meetings/minutes/<int:minutes_id>/delete", methods=["POST"])
@admin_required
def meeting_minutes_delete(minutes_id):
    conn = get_db()
    row = conn.execute("SELECT meeting_id FROM meeting_minutes WHERE id=?", (minutes_id,)).fetchone()
    if not row:
        conn.close()
        flash("Minutes not found.")
        return redirect(url_for("meetings"))
    meeting_id = row["meeting_id"]
    conn.execute("DELETE FROM meeting_minutes WHERE id=?", (minutes_id,))
    conn.commit()
    conn.close()
    flash("Minutes deleted.")
    return redirect(url_for("meeting_detail", meeting_id=meeting_id))


BUSINESS_FIELDS = ["business_name", "owner_name", "phone", "sector", "location", "date_opened", "notes"]
ASSESSMENT_FIELDS = [
    "assessment_date", "monthly_income", "monthly_profit", "monthly_expenses",
    "employees_count", "challenges", "support_needed", "notes",
]


@app.route("/businesses")
@admin_required
def businesses():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE b.business_name LIKE ? OR b.owner_name LIKE ? OR b.phone LIKE ? OR b.sector LIKE ?"
        params = [f"%{q}%"] * 4
    rows = conn.execute(f"""
        SELECT b.*, COUNT(ba.id) assessment_count, MAX(ba.assessment_date) last_assessed
        FROM businesses b
        LEFT JOIN business_assessments ba ON ba.business_id = b.id
        {where}
        GROUP BY b.id
        ORDER BY b.business_name
    """, params).fetchall()
    conn.close()
    return render_template("businesses.html", businesses=rows, q=q)


@app.route("/businesses/new", methods=["GET", "POST"])
@admin_required
def business_new():
    if request.method == "POST":
        data = request.form
        name = data.get("business_name", "").strip()
        if not name:
            flash("Business name is required.")
            return render_template("business_form.html", business=None)
        conn = get_db()
        conn.execute(
            f"INSERT INTO businesses({', '.join(BUSINESS_FIELDS)}) VALUES ({', '.join(['?'] * len(BUSINESS_FIELDS))})",
            tuple(data.get(f, "").strip() for f in BUSINESS_FIELDS)
        )
        conn.commit()
        conn.close()
        flash("Business added successfully.")
        return redirect(url_for("businesses"))
    return render_template("business_form.html", business=None)


@app.route("/businesses/<int:business_id>/edit", methods=["GET", "POST"])
@admin_required
def business_edit(business_id):
    conn = get_db()
    business = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not business:
        conn.close()
        flash("Business not found.")
        return redirect(url_for("businesses"))
    if request.method == "POST":
        data = request.form
        name = data.get("business_name", "").strip()
        if not name:
            conn.close()
            flash("Business name is required.")
            return render_template("business_form.html", business=business)
        set_clause = ", ".join(f"{f}=?" for f in BUSINESS_FIELDS)
        conn.execute(f"UPDATE businesses SET {set_clause} WHERE id=?",
                     tuple(data.get(f, "").strip() for f in BUSINESS_FIELDS) + (business_id,))
        conn.commit()
        conn.close()
        flash("Business updated successfully.")
        return redirect(url_for("business_detail", business_id=business_id))
    conn.close()
    return render_template("business_form.html", business=business)


@app.route("/businesses/<int:business_id>/delete", methods=["POST"])
@admin_required
def business_delete(business_id):
    conn = get_db()
    conn.execute("DELETE FROM businesses WHERE id=?", (business_id,))
    conn.commit()
    conn.close()
    flash("Business deleted successfully.")
    return redirect(url_for("businesses"))


@app.route("/businesses/<int:business_id>")
@admin_required
def business_detail(business_id):
    conn = get_db()
    business = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not business:
        conn.close()
        flash("Business not found.")
        return redirect(url_for("businesses"))
    assessments = conn.execute(
        "SELECT * FROM business_assessments WHERE business_id=? ORDER BY assessment_date DESC, id DESC",
        (business_id,)
    ).fetchall()
    conn.close()
    return render_template("business_detail.html", business=business, assessments=assessments)


@app.route("/businesses/<int:business_id>/assessments/new", methods=["GET", "POST"])
@admin_required
def business_assessment_new(business_id):
    conn = get_db()
    business = conn.execute("SELECT * FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not business:
        conn.close()
        flash("Business not found.")
        return redirect(url_for("businesses"))
    if request.method == "POST":
        data = request.form
        columns = ASSESSMENT_FIELDS + ["business_id", "assessed_by"]
        values = [data.get(f, "").strip() for f in ASSESSMENT_FIELDS] + [business_id, session.get("admin_id")]
        conn.execute(
            f"INSERT INTO business_assessments({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})",
            tuple(values)
        )
        conn.commit()
        conn.close()
        flash("Assessment added successfully.")
        return redirect(url_for("business_detail", business_id=business_id))
    conn.close()
    return render_template("business_assessment_form.html", business=business)


@app.route("/businesses/assessments/<int:assessment_id>/delete", methods=["POST"])
@admin_required
def business_assessment_delete(assessment_id):
    conn = get_db()
    row = conn.execute("SELECT business_id FROM business_assessments WHERE id=?", (assessment_id,)).fetchone()
    if not row:
        conn.close()
        flash("Assessment not found.")
        return redirect(url_for("businesses"))
    business_id = row["business_id"]
    conn.execute("DELETE FROM business_assessments WHERE id=?", (assessment_id,))
    conn.commit()
    conn.close()
    flash("Assessment deleted.")
    return redirect(url_for("business_detail", business_id=business_id))


def upcoming_birthdays(members, days=7):
    today = date.today()
    results = []
    for m in members:
        parts = (m["birth_date"] or "").split("-")
        if len(parts) != 3:
            continue
        try:
            month, day = int(parts[1]), int(parts[2])
            next_bday = date(today.year, month, day)
        except ValueError:
            continue
        if next_bday < today:
            try:
                next_bday = date(today.year + 1, month, day)
            except ValueError:
                continue
        days_away = (next_bday - today).days
        if 0 <= days_away <= days:
            results.append({
                "id": m["id"],
                "full_name_en": m["full_name_en"],
                "bday_date": next_bday,
                "days_away": days_away,
            })
    results.sort(key=lambda r: r["days_away"])
    return results


@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "members": conn.execute("SELECT COUNT(*) c FROM members").fetchone()["c"],
        "events": conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
        "attendance": conn.execute("SELECT COUNT(*) c FROM attendance").fetchone()["c"],
        "surveys": conn.execute("SELECT COUNT(*) c FROM surveys").fetchone()["c"],
        "meetings": conn.execute("SELECT COUNT(*) c FROM meetings").fetchone()["c"],
    }
    top_members = conn.execute("""
        SELECT m.id, m.full_name_en, m.phone,
               COUNT(a.id) total_attendances,
               COUNT(DISTINCT a.event_id) total_events
        FROM members m
        LEFT JOIN attendance a ON a.member_id = m.id
        WHERE COALESCE(m.member_type, 'member') = 'member'
        GROUP BY m.id
        ORDER BY total_attendances DESC, m.full_name_en
        LIMIT 12
    """).fetchall()
    event_counts = conn.execute("""
        SELECT e.id, e.name, COUNT(DISTINCT a.member_id) unique_attendees, COUNT(a.id) total_records
        FROM events e
        LEFT JOIN attendance a ON a.event_id=e.id
        GROUP BY e.id
        ORDER BY e.name
    """).fetchall()
    birthday_members = conn.execute("""
        SELECT id, full_name_en, birth_date FROM members
        WHERE birth_date IS NOT NULL AND birth_date <> '' AND COALESCE(member_type, 'member') = 'member'
    """).fetchall()
    conn.close()
    birthdays = upcoming_birthdays(birthday_members)
    return render_template("dashboard.html", stats=stats, top_members=top_members, event_counts=event_counts, birthdays=birthdays)


@app.route("/calendar")
@login_required
def calendar_view():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
    except ValueError:
        year, month = today.year, today.month
    if month < 1:
        month, year = 12, year - 1
    elif month > 12:
        month, year = 1, year + 1

    conn = get_db()
    events = conn.execute("SELECT id, name, event_date FROM events WHERE event_date IS NOT NULL AND event_date <> ''").fetchall()
    sessions = conn.execute("""
        SELECT s.id, s.name, s.session_date, e.name AS event_name
        FROM sessions s JOIN events e ON e.id = s.event_id
        WHERE s.session_date IS NOT NULL AND s.session_date <> ''
    """).fetchall()
    meetings_rows = conn.execute("""
        SELECT id, title, department, meeting_date FROM meetings
        WHERE meeting_date IS NOT NULL AND meeting_date <> ''
    """).fetchall()
    is_admin = session.get("admin_role") in ("admin", "owner")
    members = []
    if is_admin:
        members = conn.execute("""
            SELECT id, full_name_en, birth_date FROM members
            WHERE birth_date IS NOT NULL AND birth_date <> '' AND COALESCE(member_type, 'member') = 'member'
        """).fetchall()
    conn.close()

    items_by_day = {}

    def add_item(date_str, item):
        items_by_day.setdefault(date_str, []).append(item)

    for e in events:
        add_item(e["event_date"], {"type": "event", "title": e["name"], "url": url_for("event_attendees", event_id=e["id"])})
    for s in sessions:
        add_item(s["session_date"], {"type": "session", "title": f'{s["event_name"]} — {s["name"]}', "url": url_for("session_attendees", session_id=s["id"])})
    for mt in meetings_rows:
        title = f'{mt["department"]} — {mt["title"]}' if mt["department"] else mt["title"]
        add_item(mt["meeting_date"], {"type": "meeting", "title": title, "url": url_for("meeting_detail", meeting_id=mt["id"])})
    for m in members:
        parts = (m["birth_date"] or "").split("-")
        if len(parts) == 3:
            add_item(f"{year:04d}-{parts[1]}-{parts[2]}", {"type": "birthday", "title": f'{m["full_name_en"]}\'s Birthday', "url": url_for("member_detail", member_id=m["id"])})

    month_cal = calendar_module.Calendar(firstweekday=6)
    all_dates = list(month_cal.itermonthdates(year, month))
    weeks = []
    for week_start in range(0, len(all_dates), 7):
        week = all_dates[week_start:week_start + 7]
        week_data = []
        for d in week:
            date_str = d.isoformat()
            week_data.append({
                "day": d.day,
                "in_month": d.month == month,
                "is_today": d == today,
                "entries": items_by_day.get(date_str, []),
            })
        weeks.append(week_data)

    prev_month, prev_year = (12, year - 1) if month == 1 else (month - 1, year)
    next_month, next_year = (1, year + 1) if month == 12 else (month + 1, year)

    return render_template(
        "calendar.html",
        weeks=weeks,
        month_name=calendar_module.month_name[month],
        year=year,
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
    )


@app.route("/active-members")
@admin_required
def active_members():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = "WHERE COALESCE(m.member_type, 'member') = 'member'"
    params = []
    if q:
        where += " AND (m.full_name_en LIKE ? OR m.phone LIKE ? OR m.city LIKE ? OR m.work LIKE ? OR m.studied_where LIKE ?)"
        params = [f"%{q}%"]*5
    rows = conn.execute(f"""
        SELECT m.id, m.full_name_en, m.full_name_ar, m.phone, m.city, m.studied_where, m.work,
               COUNT(a.id) attendance_count,
               COUNT(DISTINCT a.event_id) event_count,
               GROUP_CONCAT(DISTINCT e.name) events_attended
        FROM members m
        LEFT JOIN attendance a ON a.member_id=m.id
        LEFT JOIN events e ON e.id=a.event_id
        {where}
        GROUP BY m.id
        ORDER BY attendance_count DESC, event_count DESC, m.full_name_en
    """, params).fetchall()
    conn.close()
    return render_template("active_members.html", members=rows, q=q)

@app.route("/events/<int:event_id>/attendees")
@login_required
def event_attendees(event_id):
    q = request.args.get("q", "").strip()
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))
    where = "AND (m.full_name_en LIKE ? OR m.phone LIKE ? OR m.city LIKE ? OR m.work LIKE ? OR m.studied_where LIKE ?)" if q else ""
    params = [event_id] + ([f"%{q}%"]*5 if q else [])
    attendees = conn.execute(f"""
        SELECT m.*, COUNT(a.id) attendance_count,
               GROUP_CONCAT(COALESCE(s.name, 'Full event'), ', ') session_names
        FROM attendance a
        JOIN members m ON m.id=a.member_id
        LEFT JOIN sessions s ON s.id=a.session_id
        WHERE a.event_id=? {where}
        GROUP BY m.id
        ORDER BY m.full_name_en
    """, params).fetchall()
    sessions = conn.execute("""
        SELECT s.*, COUNT(DISTINCT a.member_id) attendee_count
        FROM sessions s
        LEFT JOIN attendance a ON a.session_id=s.id
        WHERE s.event_id=?
        GROUP BY s.id
        ORDER BY s.session_date, s.name
    """, (event_id,)).fetchall()
    conn.close()
    return render_template("event_attendees.html", event=event, attendees=attendees, sessions=sessions, q=q)

@app.route("/sessions/<int:session_id>/attendees")
@login_required
def session_attendees(session_id):
    q = request.args.get("q", "").strip()
    conn = get_db()
    session_row = conn.execute("""
        SELECT s.*, e.name event_name, e.id event_id
        FROM sessions s JOIN events e ON e.id=s.event_id
        WHERE s.id=?
    """, (session_id,)).fetchone()
    if not session_row:
        conn.close()
        flash("Session not found.")
        return redirect(url_for("events"))
    where = "AND (m.full_name_en LIKE ? OR m.phone LIKE ? OR m.city LIKE ? OR m.work LIKE ? OR m.studied_where LIKE ?)" if q else ""
    params = [session_id] + ([f"%{q}%"]*5 if q else [])
    attendees = conn.execute(f"""
        SELECT m.*
        FROM attendance a
        JOIN members m ON m.id=a.member_id
        WHERE a.session_id=? {where}
        ORDER BY m.full_name_en
    """, params).fetchall()
    conn.close()
    return render_template("session_attendees.html", session_row=session_row, attendees=attendees, q=q)

@app.route("/members")
@admin_required
def members():
    q = request.args.get("q", "").strip()
    view_type = "guest" if request.args.get("type") == "guest" else "member"
    conn = get_db()
    where = "WHERE COALESCE(m.member_type, 'member') = ?"
    params = [view_type]
    if q:
        like = f"%{q}%"
        where += """ AND (m.full_name_en LIKE ? OR m.full_name_ar LIKE ? OR m.phone LIKE ? OR m.email LIKE ?
                   OR m.birth_date LIKE ? OR m.city LIKE ? OR m.studied_where LIKE ? OR m.field_of_study LIKE ? OR m.work LIKE ?)"""
        params += [like]*9
    rows = conn.execute(f"""
        SELECT m.*,
               COUNT(a.id) attendance_count,
               COUNT(DISTINCT a.event_id) event_count
        FROM members m
        LEFT JOIN attendance a ON a.member_id=m.id
        {where}
        GROUP BY m.id
        ORDER BY m.full_name_en
    """, params).fetchall()
    conn.close()
    return render_template("members.html", members=rows, q=q, view_type=view_type)


@app.route("/members/export.csv")
@admin_required
def members_export():
    q = request.args.get("q", "").strip()
    view_type = "guest" if request.args.get("type") == "guest" else "member"
    conn = get_db()
    where = "WHERE COALESCE(m.member_type, 'member') = ?"
    params = [view_type]
    if q:
        like = f"%{q}%"
        where += """ AND (m.full_name_en LIKE ? OR m.full_name_ar LIKE ? OR m.phone LIKE ? OR m.email LIKE ?
                   OR m.birth_date LIKE ? OR m.city LIKE ? OR m.studied_where LIKE ? OR m.field_of_study LIKE ? OR m.work LIKE ?)"""
        params += [like]*9
    rows = conn.execute(f"""
        SELECT m.*, COUNT(a.id) attendance_count, COUNT(DISTINCT a.event_id) event_count
        FROM members m
        LEFT JOIN attendance a ON a.member_id=m.id
        {where}
        GROUP BY m.id
        ORDER BY m.full_name_en
    """, params).fetchall()
    conn.close()
    columns = MEMBER_FIELDS + ["attendance_count", "event_count"]
    header = ["Full Name (English)", "Full Name (Arabic)", "Phone", "Email", "Birth Date", "Gender", "City",
              "Current Status", "Studied Where", "Field of Study", "Work", "English Level", "Notes",
              "Skills", "Interests", "Motivation", "Date Joined", "Blood Type", "Learn More",
              "Access to Transportation", "Emergency Contact Name", "Emergency Contact Phone", "Member Type",
              "Attendance Count", "Event Count"]
    csv_rows = [[row[col] if row[col] is not None else "" for col in columns] for row in rows]
    return csv_response(f"{view_type}s.csv", header, csv_rows)


@app.route("/members/new", methods=["GET","POST"])
@admin_required
def member_new():
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY name").fetchall()
    sessions = conn.execute("SELECT s.*, e.name event_name FROM sessions s JOIN events e ON e.id=s.event_id ORDER BY s.session_date").fetchall()
    if request.method == "POST":
        data = request.form
        if not data.get("full_name_en", "").strip():
            conn.close()
            flash("Full name is required.")
            return render_template("member_form.html", member=None, events=events, sessions=sessions, selected_events=[], selected_sessions=[])
        cur = conn.execute(f"""
            INSERT INTO members({', '.join(MEMBER_FIELDS)})
            VALUES ({', '.join(['?'] * len(MEMBER_FIELDS))}) RETURNING id
        """, tuple(member_field_value(data, k) for k in MEMBER_FIELDS))
        member_id = get_new_id(cur)
        for event_id in request.form.getlist("events"):
            add_attendance(conn, member_id, event_id)
        for session_id in request.form.getlist("sessions"):
            s = conn.execute("SELECT event_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if s:
                add_attendance(conn, member_id, s["event_id"], session_id)
        conn.commit()
        conn.close()
        flash("Member added successfully.")
        return redirect(request.form.get("next") or url_for("member_detail", member_id=member_id))
    conn.close()
    return render_template("member_form.html", member=None, events=events, sessions=sessions, selected_events=[], selected_sessions=[])

@app.route("/members/<int:member_id>")
@admin_required
def member_detail(member_id):
    conn = get_db()
    member = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    attended = conn.execute("""
        SELECT e.name event_name, e.event_date, s.name session_name, s.session_date, a.status
        FROM attendance a
        JOIN events e ON e.id=a.event_id
        LEFT JOIN sessions s ON s.id=a.session_id
        WHERE a.member_id=?
        ORDER BY e.name, s.session_date
    """, (member_id,)).fetchall()
    conn.close()
    if not member:
        flash("Member not found.")
        return redirect(url_for("members"))
    return render_template("member_detail.html", member=member, attended=attended)

@app.route("/members/<int:member_id>/edit", methods=["GET","POST"])
@admin_required
def member_edit(member_id):
    conn = get_db()
    member = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    events = conn.execute("SELECT * FROM events ORDER BY name").fetchall()
    sessions = conn.execute("SELECT s.*, e.name event_name FROM sessions s JOIN events e ON e.id=s.event_id ORDER BY s.session_date").fetchall()
    selected_events = [str(r["event_id"]) for r in conn.execute("SELECT event_id FROM attendance WHERE member_id=? AND session_id IS NULL", (member_id,)).fetchall()]
    selected_sessions = [str(r["session_id"]) for r in conn.execute("SELECT session_id FROM attendance WHERE member_id=? AND session_id IS NOT NULL", (member_id,)).fetchall()]
    if not member:
        conn.close()
        flash("Member not found.")
        return redirect(url_for("members"))
    if request.method == "POST":
        data = request.form
        if not data.get("full_name_en", "").strip():
            conn.close()
            flash("Full name is required.")
            return render_template("member_form.html", member=member, events=events, sessions=sessions, selected_events=selected_events, selected_sessions=selected_sessions)
        conn.execute(f"""
            UPDATE members SET {', '.join(f'{field}=?' for field in MEMBER_FIELDS)}
            WHERE id=?
        """, tuple(member_field_value(data, k) for k in MEMBER_FIELDS) + (member_id,))
        conn.execute("DELETE FROM attendance WHERE member_id=?", (member_id,))
        for event_id in request.form.getlist("events"):
            add_attendance(conn, member_id, event_id)
        for session_id in request.form.getlist("sessions"):
            s = conn.execute("SELECT event_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if s:
                add_attendance(conn, member_id, s["event_id"], session_id)
        conn.commit()
        conn.close()
        flash("Member updated successfully.")
        return redirect(request.form.get("next") or url_for("member_detail", member_id=member_id))
    conn.close()
    return render_template("member_form.html", member=member, events=events, sessions=sessions, selected_events=selected_events, selected_sessions=selected_sessions)

@app.route("/members/<int:member_id>/delete", methods=["POST"])
@admin_required
def member_delete(member_id):
    conn = get_db()
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    flash("Member deleted successfully.")
    return redirect(url_for("members"))

@app.route("/members/<int:member_id>/promote", methods=["POST"])
@admin_required
def member_promote(member_id):
    conn = get_db()
    member = conn.execute("SELECT full_name_en FROM members WHERE id=?", (member_id,)).fetchone()
    if not member:
        conn.close()
        flash("Member not found.")
        return redirect(url_for("members", type="guest"))
    conn.execute("UPDATE members SET member_type='member' WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    flash(f"{member['full_name_en']} is now a full member.")
    return redirect(url_for("members", type="guest"))


@app.route("/members/bulk-promote", methods=["POST"])
@admin_required
def members_bulk_promote():
    ids = request.form.getlist("member_ids")
    conn = get_db()
    for member_id in ids:
        conn.execute("UPDATE members SET member_type='member' WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    flash(f"Added {len(ids)} guest(s) as members.")
    return redirect(url_for("members", type="guest"))


@app.route("/members/bulk-delete", methods=["POST"])
@admin_required
def members_bulk_delete():
    ids = request.form.getlist("member_ids")
    view_type = "guest" if request.args.get("type") == "guest" else "member"
    conn = get_db()
    for member_id in ids:
        conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    flash(f"Deleted {len(ids)} {view_type}(s).")
    return redirect(url_for("members", type=view_type))


FIELD_ALIASES = {
    "full_name_en": ["full name", "full name (english)", "name", "english name"],
    "full_name_ar": ["full name (arabic)", "arabic name"],
    "phone": ["phone", "phone number", "mobile", "mobile number", "tel"],
    "email": ["email", "email address"],
    "birth_date": ["birth date", "birthday", "date of birth", "dob"],
    "gender": ["gender", "sex"],
    "city": ["city", "city / area", "area", "location"],
    "current_status": ["current status", "status"],
    "studied_where": ["studied where", "university", "school", "studied where / university"],
    "field_of_study": ["field of study", "major"],
    "work": ["work", "job", "occupation"],
    "english_level": ["english level"],
    "notes": ["notes", "note"],
    "skills": ["skills"],
    "interests": ["interests"],
    "motivation": ["motivation", "motivation for joining sawa"],
    "date_joined": ["date joined", "date of joining", "join date"],
    "blood_type": ["blood type"],
    "learn_more": ["learn more", "what would they like to learn more"],
    "has_transportation": ["transportation", "access to transportation"],
    "emergency_contact_name": ["emergency contact", "emergency contact name"],
    "emergency_contact_phone": ["emergency contact phone", "emergency phone"],
}


def match_column_to_field(header_text):
    h = (header_text or "").strip().lower()
    for field, aliases in FIELD_ALIASES.items():
        if h == field.replace("_", " ") or h in aliases:
            return field
    return None


@app.route("/members/import", methods=["GET", "POST"])
@admin_required
def member_import():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Please choose a CSV file to upload.")
            return redirect(url_for("member_import"))
        content = file.read().decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(content)))
        if not rows:
            flash("That file looks empty.")
            return redirect(url_for("member_import"))
        header = rows[0]
        data_rows = rows[1:]
        column_fields = [match_column_to_field(h) for h in header]

        if not any(column_fields):
            flash("Couldn't recognize any column headers — make sure the first row has names like \"Full Name\", \"Phone\", \"Email\", \"City\", etc.")
            return redirect(url_for("member_import"))

        conn = get_db()
        created = updated = skipped = 0
        for row in data_rows:
            record = {}
            for idx, field in enumerate(column_fields):
                if field and idx < len(row) and row[idx].strip():
                    record[field] = row[idx].strip()
            name = record.get("full_name_en", "")
            if not name:
                skipped += 1
                continue
            phone = record.get("phone", "")
            email = record.get("email", "")
            existing = None
            if phone:
                existing = conn.execute("SELECT * FROM members WHERE phone=?", (phone,)).fetchone()
            if not existing and email:
                existing = conn.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
            if existing:
                updates = {k: v for k, v in record.items() if v and not (existing[k] or "").strip()}
                if updates:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    conn.execute(f"UPDATE members SET {set_clause} WHERE id=?", tuple(updates.values()) + (existing["id"],))
                updated += 1
            else:
                columns = list(record.keys())
                conn.execute(
                    f"INSERT INTO members({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))})",
                    tuple(record.values())
                )
                created += 1
        conn.commit()
        conn.close()
        flash(f"Import complete: {created} added, {updated} updated, {skipped} skipped (missing name).")
        return redirect(url_for("members"))
    return render_template("member_import.html")


@app.route("/events")
@login_required
def events():
    conn = get_db()
    rows = conn.execute("""
        SELECT e.*, COUNT(DISTINCT a.member_id) unique_attendees, COUNT(a.id) attendance_records
        FROM events e
        LEFT JOIN attendance a ON a.event_id=e.id
        GROUP BY e.id
        ORDER BY e.name
    """).fetchall()
    sessions = conn.execute("SELECT s.*, e.name event_name FROM sessions s JOIN events e ON e.id=s.event_id ORDER BY e.name, s.session_date").fetchall()
    conn.close()
    return render_template("events.html", events=rows, sessions=sessions)


def save_event_questions(conn, event_id):
    conn.execute("DELETE FROM event_questions WHERE event_id=?", (event_id,))
    question_texts = request.form.getlist("question_text")
    field_types = request.form.getlist("field_type")
    sort_order = 0
    for i, q in enumerate(question_texts):
        q = q.strip()
        if not q:
            continue
        sort_order += 1
        conn.execute(
            "INSERT INTO event_questions(event_id, question_text, field_type, sort_order) VALUES (?, ?, ?, ?)",
            (event_id, q, field_types[i] if i < len(field_types) else "text", sort_order)
        )


@app.route("/events/new", methods=["GET","POST"])
@admin_required
def event_new():
    if request.method == "POST":
        data = request.form
        name = data.get("name", "").strip()
        if not name:
            flash("Event name is required.")
            return render_template("event_form.html", event=None, questions=[])
        conn = get_db()
        cur = conn.execute("INSERT INTO events(code,name,event_date,location,event_type,notes) VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
                     (None, name, data.get("event_date"), data.get("location"), data.get("event_type"), data.get("notes")))
        event_id = get_new_id(cur)
        save_event_questions(conn, event_id)
        conn.commit()
        conn.close()
        flash("Event added successfully.")
        return redirect(url_for("events"))
    return render_template("event_form.html", event=None, questions=[])

@app.route("/events/<int:event_id>/edit", methods=["GET","POST"])
@admin_required
def event_edit(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))
    if request.method == "POST":
        data = request.form
        name = data.get("name", "").strip()
        if not name:
            flash("Event name is required.")
            questions = conn.execute("SELECT * FROM event_questions WHERE event_id=? ORDER BY sort_order", (event_id,)).fetchall()
            conn.close()
            return render_template("event_form.html", event=event, questions=questions)
        conn.execute("UPDATE events SET name=?, event_date=?, location=?, event_type=?, notes=? WHERE id=?",
                     (name, data.get("event_date"), data.get("location"), data.get("event_type"), data.get("notes"), event_id))
        save_event_questions(conn, event_id)
        conn.commit()
        conn.close()
        flash("Event updated successfully.")
        return redirect(url_for("events"))
    questions = conn.execute("SELECT * FROM event_questions WHERE event_id=? ORDER BY sort_order", (event_id,)).fetchall()
    conn.close()
    return render_template("event_form.html", event=event, questions=questions)

@app.route("/events/<int:event_id>/delete", methods=["POST"])
@admin_required
def event_delete(event_id):
    conn = get_db()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    flash("Event deleted successfully.")
    return redirect(url_for("events"))

@app.route("/attendance")
@admin_required
def attendance():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE m.full_name_en LIKE ? OR e.name LIKE ? OR s.name LIKE ?"
        params = [f"%{q}%"]*3
    rows = conn.execute(f"""
        SELECT m.full_name_en, m.phone, e.name event_name, s.name session_name, s.session_date, e.event_date
        FROM attendance a
        JOIN members m ON m.id=a.member_id
        JOIN events e ON e.id=a.event_id
        LEFT JOIN sessions s ON s.id=a.session_id
        {where}
        ORDER BY e.name, s.session_date, m.full_name_en
    """, params).fetchall()
    conn.close()
    return render_template("attendance.html", rows=rows, q=q)


@app.route("/attendance/export.csv")
@admin_required
def attendance_export():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE m.full_name_en LIKE ? OR e.name LIKE ? OR s.name LIKE ?"
        params = [f"%{q}%"]*3
    rows = conn.execute(f"""
        SELECT m.full_name_en, m.phone, e.name event_name, s.name session_name, s.session_date, e.event_date
        FROM attendance a
        JOIN members m ON m.id=a.member_id
        JOIN events e ON e.id=a.event_id
        LEFT JOIN sessions s ON s.id=a.session_id
        {where}
        ORDER BY e.name, s.session_date, m.full_name_en
    """, params).fetchall()
    conn.close()
    header = ["Member", "Phone", "Event", "Session", "Session Date", "Event Date"]
    csv_rows = [
        [r["full_name_en"] or "", r["phone"] or "", r["event_name"] or "",
         r["session_name"] or "Full event", r["session_date"] or "", r["event_date"] or ""]
        for r in rows
    ]
    return csv_response("attendance.csv", header, csv_rows)


@app.route("/surveys")
@admin_required
def surveys():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = """WHERE full_name LIKE ? OR phone LIKE ? OR city LIKE ? OR university_school LIKE ?
                   OR field_work LIKE ? OR interest_reason LIKE ? OR learn_most LIKE ? OR heard_from LIKE ?"""
        params = [f"%{q}%"]*8
    rows = conn.execute(f"""
        SELECT * FROM surveys
        {where}
        ORDER BY timestamp DESC, full_name
    """, params).fetchall()
    conn.close()
    return render_template("surveys.html", surveys=rows, q=q)


@app.route("/surveys/export.csv")
@admin_required
def surveys_export():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = """WHERE full_name LIKE ? OR phone LIKE ? OR city LIKE ? OR university_school LIKE ?
                   OR field_work LIKE ? OR interest_reason LIKE ? OR learn_most LIKE ? OR heard_from LIKE ?"""
        params = [f"%{q}%"]*8
    rows = conn.execute(f"""
        SELECT * FROM surveys
        {where}
        ORDER BY timestamp DESC, full_name
    """, params).fetchall()
    conn.close()
    columns = ["survey_name", "timestamp", "full_name", "phone", "birth_date", "gender", "city",
               "current_status", "university_school", "field_work", "english_level", "interest_reason",
               "attended_before", "learn_most", "heard_from", "raw_answers"]
    header = ["Survey", "Timestamp", "Full Name", "Phone", "Birth Date", "Gender", "City", "Status",
              "University / School", "Field / Work", "English Level", "Why Interested", "Attended Before",
              "Learn Most", "Heard From", "Raw Answers"]
    csv_rows = [[row[col] or "" for col in columns] for row in rows]
    return csv_response("survey_responses.csv", header, csv_rows)


@app.route("/surveys/<int:survey_id>")
@admin_required
def survey_detail(survey_id):
    conn = get_db()
    survey = conn.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
    conn.close()
    if not survey:
        flash("Survey response not found.")
        return redirect(url_for("surveys"))
    return render_template("survey_detail.html", survey=survey)


@app.route("/survey-forms")
@admin_required
def survey_forms():
    conn = get_db()
    rows = conn.execute("""
        SELECT sf.*, COUNT(s.id) response_count
        FROM survey_forms sf
        LEFT JOIN surveys s ON s.survey_name = sf.title
        GROUP BY sf.id
        ORDER BY sf.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("survey_forms.html", survey_forms=rows)

@app.route("/survey-forms/new", methods=["GET", "POST"])
@admin_required
def survey_form_new():
    if request.method == "POST":
        data = request.form
        conn = get_db()
        cur = conn.execute(
            "INSERT INTO survey_forms(title, description, source_link, source_sheet_name, source_notes) VALUES (?, ?, ?, ?, ?) RETURNING id",
            (data.get("title", ""), data.get("description", ""), data.get("source_link", ""), data.get("source_sheet_name", ""), data.get("source_notes", ""))
        )
        form_id = get_new_id(cur)
        question_texts = request.form.getlist("question_text")
        field_types = request.form.getlist("field_type")
        for i, q in enumerate(question_texts, start=1):
            q = q.strip()
            if not q:
                continue
            conn.execute("""
                INSERT INTO survey_questions(survey_form_id, question_text, field_key, field_type, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (form_id, q, "custom_" + str(i), field_types[i-1] if i-1 < len(field_types) else "text", i))
        conn.commit()
        conn.close()
        flash("Survey created successfully.")
        return redirect(url_for("survey_forms"))
    return render_template("survey_form_builder.html", survey_form=None, questions=[])

@app.route("/survey-forms/<int:form_id>/edit", methods=["GET", "POST"])
@admin_required
def survey_form_edit(form_id):
    conn = get_db()
    survey_form = conn.execute("SELECT * FROM survey_forms WHERE id=?", (form_id,)).fetchone()
    if not survey_form:
        conn.close()
        flash("Survey not found.")
        return redirect(url_for("survey_forms"))
    if request.method == "POST":
        data = request.form
        conn.execute("UPDATE survey_forms SET title=?, description=?, source_link=?, source_sheet_name=?, source_notes=? WHERE id=?",
                     (data.get("title", ""), data.get("description", ""), data.get("source_link", ""), data.get("source_sheet_name", ""), data.get("source_notes", ""), form_id))
        conn.execute("DELETE FROM survey_questions WHERE survey_form_id=?", (form_id,))
        question_texts = request.form.getlist("question_text")
        field_types = request.form.getlist("field_type")
        for i, q in enumerate(question_texts, start=1):
            q = q.strip()
            if not q:
                continue
            conn.execute("""
                INSERT INTO survey_questions(survey_form_id, question_text, field_key, field_type, sort_order)
                VALUES (?, ?, ?, ?, ?)
            """, (form_id, q, "custom_" + str(i), field_types[i-1] if i-1 < len(field_types) else "text", i))
        conn.commit()
        conn.close()
        flash("Survey updated successfully.")
        return redirect(url_for("survey_forms"))
    questions = conn.execute("SELECT * FROM survey_questions WHERE survey_form_id=? ORDER BY sort_order", (form_id,)).fetchall()
    conn.close()
    return render_template("survey_form_builder.html", survey_form=survey_form, questions=questions)

@app.route("/survey-forms/<int:form_id>/delete", methods=["POST"])
@admin_required
def survey_form_delete(form_id):
    conn = get_db()
    conn.execute("DELETE FROM survey_forms WHERE id=?", (form_id,))
    conn.commit()
    conn.close()
    flash("Survey form deleted. Existing responses were kept.")
    return redirect(url_for("survey_forms"))

@app.route("/survey-forms/<int:form_id>/source")
@admin_required
def survey_source(form_id):
    conn = get_db()
    form = conn.execute("SELECT * FROM survey_forms WHERE id=?", (form_id,)).fetchone()
    conn.close()
    if not form or not form["source_link"]:
        flash("No source link added for this survey.")
        return redirect(url_for("survey_forms"))
    return redirect(form["source_link"])


@app.route("/survey-forms/<int:form_id>/responses/new", methods=["GET", "POST"])
@admin_required
def survey_response_new(form_id):
    conn = get_db()
    survey_form = conn.execute("SELECT * FROM survey_forms WHERE id=?", (form_id,)).fetchone()
    questions = conn.execute("SELECT * FROM survey_questions WHERE survey_form_id=? ORDER BY sort_order", (form_id,)).fetchall()
    if not survey_form:
        conn.close()
        flash("Survey not found.")
        return redirect(url_for("survey_forms"))

    if request.method == "POST":
        data = request.form
        mapped = {
            "full_name": data.get("full_name", ""),
            "phone": data.get("phone", ""),
            "birth_date": data.get("birth_date", ""),
            "gender": data.get("gender", ""),
            "city": data.get("city", ""),
            "current_status": data.get("current_status", ""),
            "university_school": data.get("university_school", ""),
            "field_work": data.get("field_work", ""),
            "english_level": data.get("english_level", ""),
            "interest_reason": data.get("interest_reason", ""),
            "attended_before": data.get("attended_before", ""),
            "learn_most": data.get("learn_most", ""),
            "heard_from": data.get("heard_from", ""),
        }
        custom_answers = []
        standard_keys = set(mapped.keys())
        for q in questions:
            answer = data.get(q["field_key"], "")
            if q["field_key"] not in standard_keys and answer:
                custom_answers.append(f'{q["question_text"]}: {answer}')
        raw_answers = " | ".join([x for x in list(mapped.values()) + custom_answers if x])

        conn.execute("""
            INSERT INTO surveys(survey_name,timestamp,full_name,phone,birth_date,gender,city,current_status,university_school,field_work,english_level,interest_reason,attended_before,learn_most,heard_from,raw_answers)
            VALUES (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            survey_form["title"], mapped["full_name"], mapped["phone"], mapped["birth_date"], mapped["gender"], mapped["city"],
            mapped["current_status"], mapped["university_school"], mapped["field_work"], mapped["english_level"],
            mapped["interest_reason"], mapped["attended_before"], mapped["learn_most"], mapped["heard_from"], raw_answers
        ))
        conn.commit()
        conn.close()
        flash("Survey response added successfully.")
        return redirect(url_for("surveys"))

    conn.close()
    return render_template("survey_response_form.html", survey_form=survey_form, questions=questions)

@app.route("/surveys/<int:survey_id>/delete", methods=["POST"])
@admin_required
def survey_response_delete(survey_id):
    conn = get_db()
    conn.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
    conn.commit()
    conn.close()
    flash("Survey response deleted successfully.")
    return redirect(url_for("surveys"))


@app.route("/signup-forms")
@admin_required
def signup_forms():
    conn = get_db()
    rows = conn.execute("""
        SELECT sf.*, e.name AS event_name, COUNT(sr.id) AS response_count
        FROM signup_forms sf
        JOIN events e ON e.id = sf.event_id
        LEFT JOIN signup_responses sr ON sr.signup_form_id = sf.id
        GROUP BY sf.id, e.name
        ORDER BY sf.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("signup_forms.html", forms=rows)


@app.route("/signup-forms/new", methods=["GET", "POST"])
@admin_required
def signup_form_new():
    conn = get_db()
    events_list = conn.execute("SELECT * FROM events ORDER BY name").fetchall()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_id = request.form.get("event_id")
        description = request.form.get("description", "").strip()
        selected_fields = [f for f in request.form.getlist("fields") if f in OPTIONAL_FIELD_KEYS]
        is_active = 1 if request.form.get("is_active") else 0
        if not title or not event_id:
            flash("Title and event are required.")
        else:
            slug = generate_unique_slug(conn)
            conn.execute(
                "INSERT INTO signup_forms(event_id, title, description, fields, slug, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, title, description, json.dumps(selected_fields), slug, is_active)
            )
            conn.commit()
            conn.close()
            flash("Sign-up form created successfully.")
            return redirect(url_for("signup_forms"))
    conn.close()
    preselect_event = request.args.get("event_id", "")
    return render_template(
        "signup_form_builder.html", form=None, events=events_list, preselect_event=preselect_event,
        selected_fields=[], field_categories=OPTIONAL_FIELD_CATEGORIES
    )


@app.route("/signup-forms/<int:form_id>/edit", methods=["GET", "POST"])
@admin_required
def signup_form_edit(form_id):
    conn = get_db()
    signup_form = conn.execute("SELECT * FROM signup_forms WHERE id=?", (form_id,)).fetchone()
    if not signup_form:
        conn.close()
        flash("Sign-up form not found.")
        return redirect(url_for("signup_forms"))
    events_list = conn.execute("SELECT * FROM events ORDER BY name").fetchall()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_id = request.form.get("event_id")
        description = request.form.get("description", "").strip()
        selected_fields = [f for f in request.form.getlist("fields") if f in OPTIONAL_FIELD_KEYS]
        is_active = 1 if request.form.get("is_active") else 0
        if not title or not event_id:
            flash("Title and event are required.")
        else:
            conn.execute(
                "UPDATE signup_forms SET event_id=?, title=?, description=?, fields=?, is_active=? WHERE id=?",
                (event_id, title, description, json.dumps(selected_fields), is_active, form_id)
            )
            conn.commit()
            conn.close()
            flash("Sign-up form updated successfully.")
            return redirect(url_for("signup_forms"))
    conn.close()
    selected_fields = json.loads(signup_form["fields"] or "[]")
    return render_template(
        "signup_form_builder.html", form=signup_form, events=events_list, preselect_event="",
        selected_fields=selected_fields, field_categories=OPTIONAL_FIELD_CATEGORIES
    )


@app.route("/signup-forms/<int:form_id>/delete", methods=["POST"])
@admin_required
def signup_form_delete(form_id):
    conn = get_db()
    conn.execute("DELETE FROM signup_forms WHERE id=?", (form_id,))
    conn.commit()
    conn.close()
    flash("Sign-up form deleted. Existing members and attendance records were kept.")
    return redirect(url_for("signup_forms"))


@app.route("/events/<int:event_id>/signup-responses")
@admin_required
def event_signup_responses(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))
    questions = conn.execute("SELECT * FROM event_questions WHERE event_id=? ORDER BY sort_order", (event_id,)).fetchall()
    responses = conn.execute("""
        SELECT sr.*, m.full_name_en, m.phone, m.city, sf.title AS form_title
        FROM signup_responses sr
        JOIN signup_forms sf ON sf.id = sr.signup_form_id
        JOIN members m ON m.id = sr.member_id
        WHERE sf.event_id = ?
        ORDER BY sr.submitted_at DESC
    """, (event_id,)).fetchall()

    answers_by_response = {}
    if questions:
        answer_rows = conn.execute("""
            SELECT sqa.signup_response_id, eq.question_text, sqa.answer_text
            FROM signup_question_answers sqa
            JOIN event_questions eq ON eq.id = sqa.event_question_id
            JOIN signup_responses sr ON sr.id = sqa.signup_response_id
            JOIN signup_forms sf ON sf.id = sr.signup_form_id
            WHERE sf.event_id = ?
            ORDER BY eq.sort_order
        """, (event_id,)).fetchall()
        for row in answer_rows:
            answers_by_response.setdefault(row["signup_response_id"], []).append(row)

    conn.close()
    return render_template("event_signup_responses.html", event=event, responses=responses, questions=questions, answers_by_response=answers_by_response)


def finish_signup(conn, signup_form, member_id, matched_existing):
    """Record attendance + a signup_response, then send them to the event's
    questions (if any) or straight to the thank-you page."""
    add_attendance(conn, member_id, signup_form["event_id"], status="Registered")
    token = generate_unique_response_token(conn)
    conn.execute(
        "INSERT INTO signup_responses(signup_form_id, member_id, matched_existing, token) VALUES (?, ?, ?, ?)",
        (signup_form["id"], member_id, matched_existing, token)
    )
    conn.commit()
    has_questions = conn.execute("SELECT id FROM event_questions WHERE event_id=?", (signup_form["event_id"],)).fetchone()
    conn.close()
    if has_questions:
        return redirect(url_for("public_signup_questions", slug=signup_form["slug"], token=token))
    return render_template("signup_thankyou.html", form=signup_form, matched_existing=matched_existing)


@app.route("/signup/<slug>", methods=["GET", "POST"])
def public_signup(slug):
    conn = get_db()
    signup_form = conn.execute("""
        SELECT sf.*, e.name AS event_name
        FROM signup_forms sf JOIN events e ON e.id = sf.event_id
        WHERE sf.slug=?
    """, (slug,)).fetchone()
    if not signup_form or not signup_form["is_active"]:
        conn.close()
        return render_template("signup_unavailable.html"), 404

    selected_keys = json.loads(signup_form["fields"] or "[]")
    active_field_keys = ALWAYS_FIELD_KEYS + [f for f in selected_keys if f in OPTIONAL_FIELD_KEYS]
    active_fields = [f for f in MEMBER_FIELD_META if f["key"] in active_field_keys]

    if request.method == "POST":
        if request.form.get("website"):
            conn.close()
            return render_template("signup_thankyou.html", form=signup_form)

        stage = request.form.get("stage", "lookup")

        if stage == "lookup":
            # Step 1: check if they're already a member by phone or email, so
            # existing members never have to re-enter details we already have.
            identifier = request.form.get("identifier", "").strip()
            if not identifier:
                conn.close()
                flash("Enter your phone number or email to continue.")
                return render_template("signup_lookup.html", form=signup_form)

            existing = conn.execute("SELECT * FROM members WHERE phone=? OR email=?", (identifier, identifier)).fetchone()
            if existing:
                return finish_signup(conn, signup_form, existing["id"], matched_existing=1)

            conn.close()
            flash("We couldn't find you in our records — please fill in your details below.")
            prefill = {"email": identifier} if "@" in identifier else {"phone": identifier}
            return render_template("signup_public.html", form=signup_form, field_categories=fields_by_category(active_fields), values=prefill)

        # Step 2: not an existing member (or the lookup didn't recognize them) — collect full details.
        submitted = {f["key"]: request.form.get(f["key"], "").strip() for f in active_fields}
        full_name_en = submitted.get("full_name_en", "")
        phone = submitted.get("phone", "")
        email = submitted.get("email", "")

        if not full_name_en or not (phone or email):
            conn.close()
            flash("Full name and at least one of phone or email are required.")
            return render_template("signup_public.html", form=signup_form, field_categories=fields_by_category(active_fields), values=request.form)

        # Phone is the primary way we identify a returning member; not everyone
        # has an email, and not everyone has a phone, so fall back to whichever
        # one was actually provided.
        if phone:
            existing = conn.execute("SELECT * FROM members WHERE phone=?", (phone,)).fetchone()
        else:
            existing = conn.execute("SELECT * FROM members WHERE email=?", (email,)).fetchone()
        if existing:
            member_id = existing["id"]
            updates = {k: v for k, v in submitted.items() if v and not (existing[k] or "").strip()}
            if updates:
                set_clause = ", ".join(f"{k}=?" for k in updates)
                conn.execute(f"UPDATE members SET {set_clause} WHERE id=?", tuple(updates.values()) + (member_id,))
            matched_existing = 1
        else:
            insert_fields = dict(submitted)
            insert_fields["date_joined"] = date.today().isoformat()
            # Brand-new sign-ups are guests, not full members — someone who
            # shows up to one event and never comes back shouldn't clutter
            # the curated Members list. An admin can promote them later.
            insert_fields["member_type"] = "guest"
            columns = list(insert_fields.keys())
            cur = conn.execute(
                f"INSERT INTO members({', '.join(columns)}) VALUES ({', '.join(['?'] * len(columns))}) RETURNING id",
                tuple(insert_fields.values())
            )
            member_id = get_new_id(cur)
            matched_existing = 0

        return finish_signup(conn, signup_form, member_id, matched_existing)

    conn.close()
    return render_template("signup_lookup.html", form=signup_form)


@app.route("/signup/<slug>/questions/<token>", methods=["GET", "POST"])
def public_signup_questions(slug, token):
    conn = get_db()
    response_row = conn.execute("""
        SELECT sr.id, sr.matched_existing, sf.event_id, sf.slug, sf.title, e.name AS event_name
        FROM signup_responses sr
        JOIN signup_forms sf ON sf.id = sr.signup_form_id
        JOIN events e ON e.id = sf.event_id
        WHERE sr.token=? AND sf.slug=?
    """, (token, slug)).fetchone()
    if not response_row:
        conn.close()
        return render_template("signup_unavailable.html"), 404

    questions = conn.execute(
        "SELECT * FROM event_questions WHERE event_id=? ORDER BY sort_order",
        (response_row["event_id"],)
    ).fetchall()

    if request.method == "POST":
        conn.execute("DELETE FROM signup_question_answers WHERE signup_response_id=?", (response_row["id"],))
        for q in questions:
            answer = request.form.get(f"question_{q['id']}", "").strip()
            if answer:
                conn.execute(
                    "INSERT INTO signup_question_answers(signup_response_id, event_question_id, answer_text) VALUES (?, ?, ?)",
                    (response_row["id"], q["id"], answer)
                )
        conn.commit()
        conn.close()
        return render_template("signup_thankyou.html", form=response_row)

    conn.close()
    return render_template("signup_questions.html", form=response_row, questions=questions)


@app.route("/events/<int:event_id>/sessions/new", methods=["GET", "POST"])
@admin_required
def session_new(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        session_date = request.form.get("session_date", "").strip()
        notes = request.form.get("notes", "").strip()
        if not name:
            flash("Session name is required.")
        else:
            conn.execute(
                "INSERT INTO sessions(event_id, name, session_date, notes) VALUES (?, ?, ?, ?)",
                (event_id, name, session_date, notes)
            )
            conn.commit()
            conn.close()
            flash("Session added successfully.")
            return redirect(url_for("event_sessions", event_id=event_id))

    conn.close()
    return render_template("session_form.html", event=event, session_row=None)

@app.route("/events/<int:event_id>/sessions")
@login_required
def event_sessions(event_id):
    q = request.args.get("q", "").strip()
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))

    sessions = conn.execute("""
        SELECT s.*, COUNT(a.id) attendance_count
        FROM sessions s
        LEFT JOIN attendance a ON a.session_id = s.id
        WHERE s.event_id=?
        GROUP BY s.id
        ORDER BY s.session_date, s.name
    """, (event_id,)).fetchall()

    where = "WHERE a.event_id=?"
    params = [event_id]
    if q:
        where += " AND (m.full_name_en LIKE ? OR m.full_name_ar LIKE ? OR m.phone LIKE ? OR s.name LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%"])

    attendees = conn.execute(f"""
        SELECT a.id attendance_id, m.id member_id, m.full_name_en, m.full_name_ar, m.phone,
               s.name session_name, s.session_date
        FROM attendance a
        JOIN members m ON m.id = a.member_id
        LEFT JOIN sessions s ON s.id = a.session_id
        {where}
        ORDER BY COALESCE(s.session_date, ''), s.name, m.full_name_en
    """, params).fetchall()

    conn.close()
    return render_template("event_sessions.html", event=event, sessions=sessions, attendees=attendees, q=q)

@app.route("/sessions/<int:session_id>/edit", methods=["GET", "POST"])
@admin_required
def session_edit(session_id):
    conn = get_db()
    session_row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session_row:
        conn.close()
        flash("Session not found.")
        return redirect(url_for("events"))

    event = conn.execute("SELECT * FROM events WHERE id=?", (session_row["event_id"],)).fetchone()

    if request.method == "POST":
        conn.execute(
            "UPDATE sessions SET name=?, session_date=?, notes=? WHERE id=?",
            (request.form.get("name", ""), request.form.get("session_date", ""), request.form.get("notes", ""), session_id)
        )
        conn.commit()
        conn.close()
        flash("Session updated successfully.")
        return redirect(url_for("event_sessions", event_id=session_row["event_id"]))

    conn.close()
    return render_template("session_form.html", event=event, session_row=session_row)

@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
@admin_required
def session_delete(session_id):
    conn = get_db()
    session_row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
    if not session_row:
        conn.close()
        flash("Session not found.")
        return redirect(url_for("events"))
    event_id = session_row["event_id"]
    conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
    conn.commit()
    conn.close()
    flash("Session deleted successfully.")
    return redirect(url_for("event_sessions", event_id=event_id))

@app.route("/events/<int:event_id>/attendees/add", methods=["GET", "POST"])
@admin_required
def event_attendee_add(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))

    sessions = conn.execute("SELECT * FROM sessions WHERE event_id=? ORDER BY session_date, name", (event_id,)).fetchall()
    members = conn.execute("""
        SELECT id, full_name_en, full_name_ar, phone
        FROM members
        ORDER BY full_name_en
    """).fetchall()

    if request.method == "POST":
        member_id = request.form.get("member_id")
        session_id = request.form.get("session_id") or None

        if not member_id:
            conn.close()
            flash("Please select an existing member or create a new one.")
            return redirect(url_for("event_attendee_add", event_id=event_id))

        add_attendance(conn, member_id, event_id, session_id)
        conn.commit()
        conn.close()
        flash("Attendance saved successfully.")
        return redirect(url_for("event_sessions", event_id=event_id))

    conn.close()
    return render_template("add_attendee.html", event=event, sessions=sessions, members=members)

@app.route("/events/<int:event_id>/take-attendance", methods=["GET", "POST"], defaults={"session_id": None})
@app.route("/sessions/<int:session_id>/take-attendance", methods=["GET", "POST"], defaults={"event_id": None})
@login_required
def take_attendance(event_id, session_id):
    conn = get_db()
    session_row = None
    if session_id:
        session_row = conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session_row:
            conn.close()
            flash("Session not found.")
            return redirect(url_for("events"))
        event_id = session_row["event_id"]
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not event:
        conn.close()
        flash("Event not found.")
        return redirect(url_for("events"))

    if request.method == "POST":
        checked_ids = set(request.form.getlist("member_ids"))
        if session_id:
            conn.execute("DELETE FROM attendance WHERE session_id=?", (session_id,))
        else:
            conn.execute("DELETE FROM attendance WHERE event_id=? AND session_id IS NULL", (event_id,))
        for member_id in checked_ids:
            add_attendance(conn, member_id, event_id, session_id, status="Present")
        conn.commit()
        conn.close()
        flash("Attendance saved successfully.")
        if session_id:
            return redirect(url_for("event_sessions", event_id=event_id))
        return redirect(url_for("event_attendees", event_id=event_id))

    members = conn.execute("SELECT id, full_name_en, full_name_ar, phone FROM members ORDER BY full_name_en").fetchall()
    if session_id:
        present_ids = {str(r["member_id"]) for r in conn.execute("SELECT member_id FROM attendance WHERE session_id=?", (session_id,)).fetchall()}
    else:
        present_ids = {str(r["member_id"]) for r in conn.execute("SELECT member_id FROM attendance WHERE event_id=? AND session_id IS NULL", (event_id,)).fetchall()}
    conn.close()
    return render_template(
        "take_attendance.html", event=event, session_row=session_row, members=members, present_ids=present_ids
    )


@app.route("/attendance/<int:attendance_id>/delete", methods=["POST"])
@admin_required
def attendance_delete(attendance_id):
    conn = get_db()
    row = conn.execute("SELECT event_id FROM attendance WHERE id=?", (attendance_id,)).fetchone()
    if not row:
        conn.close()
        flash("Attendance record not found.")
        return redirect(url_for("events"))
    event_id = row["event_id"]
    conn.execute("DELETE FROM attendance WHERE id=?", (attendance_id,))
    conn.commit()
    conn.close()
    flash("Attendance record removed.")
    return redirect(url_for("event_sessions", event_id=event_id))


if __name__ == "__main__":
    ensure_schema_ready()
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
