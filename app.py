import os

from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import psycopg2
import psycopg2.extras
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "crm.sqlite"
DATABASE_URL = os.environ.get("DATABASE_URL")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_admins():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    try:
        return cur.lastrowid
    except AttributeError:
        row = cur.fetchone()
        if row:
            return row.get("id") if isinstance(row, dict) else row[0]
        return None

def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/login", methods=["GET", "POST"])
def login():
    init_admins()
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
@login_required
def admins():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "admin").strip() or "admin"
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
            except sqlite3.IntegrityError:
                flash("This username already exists.")
    rows = conn.execute("SELECT id, username, full_name, role, created_at FROM admins ORDER BY username").fetchall()
    conn.close()
    return render_template("admins.html", admins=rows)

@app.route("/admins/<int:admin_id>/delete", methods=["POST"])
@login_required
def admin_delete(admin_id):
    if admin_id == session.get("admin_id"):
        flash("You cannot delete your own admin account while logged in.")
        return redirect(url_for("admins"))
    conn = get_db()
    conn.execute("DELETE FROM admins WHERE id=?", (admin_id,))
    conn.commit()
    conn.close()
    flash("Admin deleted successfully.")
    return redirect(url_for("admins"))

@app.route("/")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "members": conn.execute("SELECT COUNT(*) c FROM members").fetchone()["c"],
        "events": conn.execute("SELECT COUNT(*) c FROM events").fetchone()["c"],
        "sessions": conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"],
        "attendance": conn.execute("SELECT COUNT(*) c FROM attendance").fetchone()["c"],
        "surveys": conn.execute("SELECT COUNT(*) c FROM surveys").fetchone()["c"],
    }
    top_members = conn.execute("""
        SELECT m.id, m.full_name_en, m.phone,
               COUNT(a.id) total_attendances,
               COUNT(DISTINCT a.event_id) total_events
        FROM members m
        LEFT JOIN attendance a ON a.member_id = m.id
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
    conn.close()
    return render_template("dashboard.html", stats=stats, top_members=top_members, event_counts=event_counts)


@app.route("/active-members")
def active_members():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        where = "WHERE m.full_name_en LIKE ? OR m.phone LIKE ? OR m.city LIKE ? OR m.work LIKE ? OR m.studied_where LIKE ?"
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
    session = conn.execute("""
        SELECT s.*, e.name event_name, e.id event_id
        FROM sessions s JOIN events e ON e.id=s.event_id
        WHERE s.id=?
    """, (session_id,)).fetchone()
    if not session:
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
    return render_template("session_attendees.html", session=session, attendees=attendees, q=q)

@app.route("/members")
@login_required
def members():
    q = request.args.get("q", "").strip()
    conn = get_db()
    where = ""
    params = []
    if q:
        like = f"%{q}%"
        where = """WHERE m.full_name_en LIKE ? OR m.full_name_ar LIKE ? OR m.phone LIKE ? OR m.email LIKE ?
                   OR m.birth_date LIKE ? OR m.city LIKE ? OR m.studied_where LIKE ? OR m.field_of_study LIKE ? OR m.work LIKE ?"""
        params = [like]*9
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
    return render_template("members.html", members=rows, q=q)

@app.route("/members/new", methods=["GET","POST"])
@login_required
def member_new():
    conn = get_db()
    events = conn.execute("SELECT * FROM events ORDER BY name").fetchall()
    sessions = conn.execute("SELECT s.*, e.name event_name FROM sessions s JOIN events e ON e.id=s.event_id ORDER BY s.session_date").fetchall()
    if request.method == "POST":
        data = request.form
        cur = conn.execute("""
            INSERT INTO members(full_name_en, full_name_ar, phone, email, birth_date, gender, city, current_status, studied_where, field_of_study, work, english_level, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
        """, tuple(data.get(k, "") for k in ["full_name_en","full_name_ar","phone","email","birth_date","gender","city","current_status","studied_where","field_of_study","work","english_level","notes"]))
        member_id = get_new_id(cur)
        for event_id in request.form.getlist("events"):
            conn.execute("INSERT OR IGNORE INTO attendance(member_id,event_id,session_id,status) VALUES (?, ?, NULL, 'Present')", (member_id, event_id))
        for session_id in request.form.getlist("sessions"):
            s = conn.execute("SELECT event_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if s:
                conn.execute("INSERT OR IGNORE INTO attendance(member_id,event_id,session_id,status) VALUES (?, ?, ?, 'Present')", (member_id, s["event_id"], session_id))
        conn.commit()
        conn.close()
        flash("Member added successfully.")
        return redirect(request.form.get("next") or url_for("member_detail", member_id=member_id))
    conn.close()
    return render_template("member_form.html", member=None, events=events, sessions=sessions, selected_events=[], selected_sessions=[])

@app.route("/members/<int:member_id>")
@login_required
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
@login_required
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
        conn.execute("""
            UPDATE members SET full_name_en=?, full_name_ar=?, phone=?, email=?, birth_date=?, gender=?, city=?, current_status=?, studied_where=?, field_of_study=?, work=?, english_level=?, notes=?
            WHERE id=?
        """, tuple(data.get(k, "") for k in ["full_name_en","full_name_ar","phone","email","birth_date","gender","city","current_status","studied_where","field_of_study","work","english_level","notes"]) + (member_id,))
        conn.execute("DELETE FROM attendance WHERE member_id=?", (member_id,))
        for event_id in request.form.getlist("events"):
            conn.execute("INSERT OR IGNORE INTO attendance(member_id,event_id,session_id,status) VALUES (?, ?, NULL, 'Present')", (member_id, event_id))
        for session_id in request.form.getlist("sessions"):
            s = conn.execute("SELECT event_id FROM sessions WHERE id=?", (session_id,)).fetchone()
            if s:
                conn.execute("INSERT OR IGNORE INTO attendance(member_id,event_id,session_id,status) VALUES (?, ?, ?, 'Present')", (member_id, s["event_id"], session_id))
        conn.commit()
        conn.close()
        flash("Member updated successfully.")
        return redirect(request.form.get("next") or url_for("member_detail", member_id=member_id))
    conn.close()
    return render_template("member_form.html", member=member, events=events, sessions=sessions, selected_events=selected_events, selected_sessions=selected_sessions)

@app.route("/members/<int:member_id>/delete", methods=["POST"])
@login_required
def member_delete(member_id):
    conn = get_db()
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()
    conn.close()
    flash("Member deleted successfully.")
    return redirect(url_for("members"))

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

@app.route("/events/new", methods=["GET","POST"])
@login_required
def event_new():
    if request.method == "POST":
        data = request.form
        conn = get_db()
        conn.execute("INSERT INTO events(code,name,event_date,location,event_type,notes) VALUES (?, ?, ?, ?, ?, ?)",
                     (None, data.get("name"), data.get("event_date"), data.get("location"), data.get("event_type"), data.get("notes")))
        conn.commit()
        conn.close()
        flash("Event added successfully.")
        return redirect(url_for("events"))
    return render_template("event_form.html", event=None)

@app.route("/events/<int:event_id>/edit", methods=["GET","POST"])
@login_required
def event_edit(event_id):
    conn = get_db()
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if request.method == "POST":
        data = request.form
        conn.execute("UPDATE events SET name=?, event_date=?, location=?, event_type=?, notes=? WHERE id=?",
                     (data.get("name"), data.get("event_date"), data.get("location"), data.get("event_type"), data.get("notes"), event_id))
        conn.commit()
        conn.close()
        flash("Event updated successfully.")
        return redirect(url_for("events"))
    conn.close()
    return render_template("event_form.html", event=event)

@app.route("/events/<int:event_id>/delete", methods=["POST"])
@login_required
def event_delete(event_id):
    conn = get_db()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()
    flash("Event deleted successfully.")
    return redirect(url_for("events"))

@app.route("/attendance")
@login_required
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

@app.route("/surveys")
@login_required
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

@app.route("/surveys/<int:survey_id>")
@login_required
def survey_detail(survey_id):
    conn = get_db()
    survey = conn.execute("SELECT * FROM surveys WHERE id=?", (survey_id,)).fetchone()
    conn.close()
    if not survey:
        flash("Survey response not found.")
        return redirect(url_for("surveys"))
    return render_template("survey_detail.html", survey=survey)


@app.route("/survey-forms")
@login_required
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
@login_required
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
@login_required
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
@login_required
def survey_form_delete(form_id):
    conn = get_db()
    conn.execute("DELETE FROM survey_forms WHERE id=?", (form_id,))
    conn.commit()
    conn.close()
    flash("Survey form deleted. Existing responses were kept.")
    return redirect(url_for("survey_forms"))

@app.route("/survey-forms/<int:form_id>/source")
@login_required
def survey_source(form_id):
    conn = get_db()
    form = conn.execute("SELECT * FROM survey_forms WHERE id=?", (form_id,)).fetchone()
    conn.close()
    if not form or not form["source_link"]:
        flash("No source link added for this survey.")
        return redirect(url_for("survey_forms"))
    return redirect(form["source_link"])


@app.route("/survey-forms/<int:form_id>/responses/new", methods=["GET", "POST"])
@login_required
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
@login_required
def survey_response_delete(survey_id):
    conn = get_db()
    conn.execute("DELETE FROM surveys WHERE id=?", (survey_id,))
    conn.commit()
    conn.close()
    flash("Survey response deleted successfully.")
    return redirect(url_for("surveys"))



@app.route("/events/<int:event_id>/sessions/new", methods=["GET", "POST"])
@login_required
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
    return render_template("session_form.html", event=event, session=None)

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
@login_required
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
    return render_template("session_form.html", event=event, session=session_row)

@app.route("/sessions/<int:session_id>/delete", methods=["POST"])
@login_required
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
@login_required
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

        conn.execute(
            "INSERT OR IGNORE INTO attendance(member_id, event_id, session_id, status) VALUES (?, ?, ?, 'Present')",
            (member_id, event_id, session_id)
        )
        conn.commit()
        conn.close()
        flash("Attendance saved successfully.")
        return redirect(url_for("event_sessions", event_id=event_id))

    conn.close()
    return render_template("add_attendee.html", event=event, sessions=sessions, members=members)

@app.route("/attendance/<int:attendance_id>/delete", methods=["POST"])
@login_required
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
    init_admins()
    app.run(debug=True)
