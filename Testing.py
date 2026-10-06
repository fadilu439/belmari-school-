import os
import json
import sqlite3
from functools import wraps

from flask import Flask, flash, g, redirect, render_template_string, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")
DATABASE_URL = os.environ.get("DATABASE_URL")
DATABASE = os.path.join(os.path.dirname(__file__), "school.db")
CLASS_NAMES = (
    "ABU AMR",
    "ABU JA'AFAR",
    "ALIYUL KISA'I",
    "KALAF",
    "HISHAM",
    "ASEEM",
    "IBN KASEER",
    "WARSH",
    "SHU'UBA",
    "QALUN(A)",
    "QALUN(B)",
    "IBN AMIR",
    "NAFI'U",
    "ABUL HARIS",
    "KALLAD",
    "HAFS",
)
SUBJECTS = (
    "HADITH",
    "FIQIHU",
    "TAUHID",
    "SIRAH",
    "AZKAR",
    "HURUF",
    "ARABIYYA",
    "ULUMUL-QUR'AN",
)
WEEKDAYS = ("Asabar", "Lahadi", "Litinin", "Talata", "Laraba")


class DBAdapter:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, query, params=()):
        if isinstance(self.connection, sqlite3.Connection):
            return self.connection.execute(query, params)
        import psycopg2.extras
        cursor = self.connection.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute(query.replace("?", "%s"), params)
        return cursor

    def executescript(self, script):
        if isinstance(self.connection, sqlite3.Connection):
            return self.connection.executescript(script)
        for statement in [s.strip() for s in script.split(";") if s.strip()]:
            with self.connection.cursor() as cursor:
                cursor.execute(statement)
        return None

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


def use_postgres():
    return bool(DATABASE_URL)


def get_db():
    if "db" not in g:
        if use_postgres():
            import psycopg2
            g.db = DBAdapter(psycopg2.connect(DATABASE_URL))
        else:
            connection = sqlite3.connect(DATABASE)
            connection.row_factory = sqlite3.Row
            g.db = DBAdapter(connection)
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    if use_postgres():
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                full_name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS students (
                id SERIAL PRIMARY KEY,
                admission_no TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                gender TEXT,
                date_of_birth TEXT,
                class_name TEXT,
                parent_name TEXT NOT NULL,
                parent_phone TEXT NOT NULL,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(author_id) REFERENCES users(id)
            );
            """
        )
    else:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'staff',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admission_no TEXT UNIQUE NOT NULL,
                full_name TEXT NOT NULL,
                gender TEXT,
                date_of_birth TEXT,
                class_name TEXT,
                parent_name TEXT NOT NULL,
                parent_phone TEXT NOT NULL,
                address TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(author_id) REFERENCES users(id)
            );
            """
        )

    profile_columns = {
        "phone": "TEXT",
        "school_position": "TEXT",
        "homeroom_class": "TEXT",
        "teaching_classes": "TEXT NOT NULL DEFAULT '[]'",
        "subjects": "TEXT NOT NULL DEFAULT '[]'",
        "weekdays": "TEXT NOT NULL DEFAULT '[]'",
    }
    if use_postgres():
        for column_name, definition in profile_columns.items():
            db.execute(
                f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column_name} {definition}"
            )
    else:
        existing_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()
        }
        for column_name, definition in profile_columns.items():
            if column_name not in existing_columns:
                db.execute(
                    f"ALTER TABLE users ADD COLUMN {column_name} {definition}"
                )

    if use_postgres():
        admin = db.execute("SELECT id FROM users WHERE username = %s", ("admin",)).fetchone()
        if admin is None:
            db.execute(
                "INSERT INTO users (full_name, username, password_hash, role) VALUES (%s, %s, %s, %s)",
                ("Main Administrator", "admin", generate_password_hash("admin123"), "admin"),
            )
    else:
        admin = db.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
        if admin is None:
            db.execute(
                "INSERT INTO users (full_name, username, password_hash, role) VALUES (?, ?, ?, ?)",
                ("Main Administrator", "admin", generate_password_hash("admin123"), "admin"),
            )
    db.commit()


@app.before_request
def prepare_request():
    init_db()
    g.user = None
    if session.get("user_id"):
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["role"] != "admin":
            flash("This section is for the main administrator only.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)

    return wrapped_view


BASE_HTML = '''
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} - MADRASATU BELMARI</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
:root{--bg:#f8f9ff;--paper:#fff;--ink:#0f172a;--muted:#64748b;--primary:#0b2a5b;--primary-dark:#081f43;--border:#dbe3f5;--sidebar:#0a2142;--sidebar-soft:#12346a;--success-bg:#ecfdf5;--error-bg:#fef2f2;--shadow:0 20px 50px rgba(11,42,91,.12)}
*{box-sizing:border-box} body{margin:0; background:var(--bg); color:var(--ink); font-family:'Inter',sans-serif; line-height:1.5}
a{color:inherit; text-decoration:none} .layout{min-height:100vh; display:flex}
aside{width:270px; background:linear-gradient(180deg,var(--sidebar) 0%,var(--sidebar-soft) 100%); color:#edf5ff; padding:24px 16px}
.brand-wrap{display:flex; align-items:center; gap:12px; padding:10px 4px 18px; margin-bottom:18px; border-bottom:1px solid rgba(255,255,255,.1)}
.brand-mark{width:46px; height:46px; border-radius:12px; background:white; color:var(--primary); display:grid; place-items:center; font-weight:900; font-size:20px}
.brand{font-size:12.5px; font-weight:800; line-height:1.3; color:white} .welcome{color:#9fb6d8; font-size:13px; margin-bottom:16px}
nav a{display:block; padding:11px 14px; border-radius:10px; margin:4px 0; color:#a9bddf; font-weight:600; font-size:14px}
nav a:hover,nav a.active{background:rgba(255,255,255,.10); color:white}
main{flex:1; padding:30px; max-width:1500px} h1{font-size:28px; font-weight:800; color:var(--primary); margin:0}
.grid{display:grid; grid-template-columns:repeat(4,1fr); gap:18px; margin-bottom:24px}
.card,.stat{border-radius:16px; padding:24px; box-shadow:var(--shadow); background:#fff; border:1px solid var(--border)}
.stat{border-top:4px solid var(--primary)} .stat strong{display:block; font-size:32px; margin-top:8px; color:var(--primary); font-weight:800}
.button{border:0; border-radius:10px; padding:12px 20px; background:var(--primary); color:white; font-weight:700; display:inline-block}
table{width:100%; border-collapse:collapse; background:white; border-radius:14px; overflow:hidden; box-shadow:var(--shadow)}
th,td{padding:14px 18px; border-bottom:1px solid var(--border); text-align:left} th{background:#f1f5fb; font-size:13px; text-transform:uppercase}
.flash{padding:12px 15px; border-radius:10px; background:var(--success-bg); margin-bottom:15px} .flash.error{background:var(--error-bg)}
.login-page{min-height:100vh; display:grid; place-items:center; padding:20px; background:radial-gradient(1000px 500px at 20% 0%, #1a4fb0 0%, #0b2a5b 70%, #081d40 100%)}
.login-box{width:min(420px,100%); background:white; padding:36px 32px; border-radius:20px; box-shadow:0 24px 60px rgba(0,0,0,.25)}
</style>
</head>
<body>
{% if g.user %}<div class="layout"><aside><div class="brand-wrap"><div class="brand-mark">Q</div><div class="brand">MADRASATU BELMARI<br>QUR'ANIC SCHOOL</div></div><div class="welcome">Welcome, {{ g.user['full_name'] }}</div><nav>
<a href="{{ url_for('dashboard') }}" class="{{ 'active' if page == 'dashboard' else '' }}">Dashboard</a>
<a href="{{ url_for('students') }}" class="{{ 'active' if page == 'students' else '' }}">Students</a>
<a href="{{ url_for('classes') }}" class="{{ 'active' if page == 'classes' else '' }}">Classes</a>
<a href="{{ url_for('staff_directory') }}" class="{{ 'active' if page == 'staff' else '' }}">Staff directory</a>
<a href="{{ url_for('announcements') }}" class="{{ 'active' if page == 'announcements' else '' }}">Announcements</a>
{% if g.user['role'] == 'admin' %}<a href="{{ url_for('users') }}" class="{{ 'active' if page == 'users' else '' }}">Staff & Admin</a>{% endif %}
<a href="{{ url_for('logout') }}">Log out</a>
</nav></aside><main>
{% else %}<div class="login-page"><div class="login-box">{% endif %}
{% with messages = get_flashed_messages(with_categories=true) %}{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}{% endwith %}
{{ content|safe }}
{% if g.user %}</main></div>{% else %}</div></div>{% endif %}
</body></html>
'''


def page(content, title, page_name, **context):
    rendered_content = render_template_string(content, **context)
    return render_template_string(BASE_HTML, content=rendered_content, title=title, page=page_name)


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (request.form["username"].strip(),)).fetchone()
        if user and check_password_hash(user["password_hash"], request.form["password"]):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        flash("The username or password is incorrect.", "error")
    return page("""
    <div class="login-logo">
      <div class="login-mark">Q</div>
      <div>
        <div class="school-name">MADRASATU BELMARI</div>
        <div class="brand-subtitle">QUR'ANIC SCHOOL</div>
      </div>
    </div>
    <div class="brand-subtitle" style="margin-top:-4px;">Staff portal access</div>
    <form method="post">
      <div class="field"><label>Username</label><input name="username" required autofocus></div><br>
      <div class="field"><label>Password</label><input type="password" name="password" required></div><br>
      <button>Log in</button>
    </form>
    <p class="muted" style="margin-top:18px;">Contact administrator for access.</p>


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    db = get_db()
    if use_postgres():
        new_students_sql = "SELECT COUNT(*) FROM students WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'"
    else:
        new_students_sql = "SELECT COUNT(*) FROM students WHERE created_at >= date('now','-30 day')"

    stats = {"students": db.execute("SELECT COUNT(*) FROM students WHERE status='active'").fetchone()[0],
             "staff": db.execute("SELECT COUNT(*) FROM users").fetchone()[0],
             "announcements": db.execute("SELECT COUNT(*) FROM announcements").fetchone()[0],
             "new_students": db.execute(new_students_sql).fetchone()[0]}
    latest = db.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 3").fetchall()
    return page("""
    <div class="topbar"><div><h1>Dashboard</h1><p class="muted">School performance overview</p></div><a class="button" href="{{ url_for('student_new') }}">+ Add student</a></div>
    <div class="grid">{% for label, value in [('Active students', stats.students), ('Staff members', stats.staff), ('Announcements', stats.announcements), ('New students (30 days)', stats.new_students)] %}<div class="card stat"><span class="muted">{{ label }}</span><strong>{{ value }}</strong></div>{% endfor %}</div>
    <a class="card" href="{{ url_for('classes') }}" style="display:block; margin-bottom:24px;"><h2>Classes and student lists</h2><p class="muted">Browse students grouped by class.</p><span class="button">View classes</span></a>
    <a class="card" href="{{ url_for('staff_directory') }}" style="display:block; margin-bottom:24px;"><h2>Staff directory</h2><p class="muted">View staff contact, role, classes, subjects, and days.</p><span class="button">View staff</span></a>
    <div class="card"><h2>Latest announcements</h2>{% for item in latest %}<div class="announcement"><h3>{{ item['title'] }}</h3><p>{{ item['body'] }}</p><small class="muted">{{ item['created_at'] }}</small></div>{% else %}<p class="muted">No announcements yet.</p>{% endfor %}</div>
    """, "Dashboard", "dashboard", stats=stats, latest=latest)


@app.route("/students")
@login_required
def students():
    query = request.args.get("q", "").strip()
    if query:
        like = f"%{query}%"
        rows = get_db().execute(
            """SELECT * FROM students
               WHERE lower(admission_no) LIKE lower(?)
                  OR lower(full_name) LIKE lower(?)
                  OR lower(parent_name) LIKE lower(?)
                  OR lower(parent_phone) LIKE lower(?)
               ORDER BY id DESC""",
            (like, like, like, like),
        ).fetchall()
    else:
        rows = get_db().execute("SELECT * FROM students ORDER BY id DESC").fetchall()
    return page("""
            <div class="topbar"><div><h1>Student Records</h1><p class="muted">Search by admission number, student name, parent, or phone number.</p></div><a class="button" href="{{ url_for('student_new') }}">+ Add student</a></div>
            <form class="toolbar"><input class="search" name="q" value="{{ query }}" placeholder="Search students..." autofocus><button>Search</button>{% if query %}<a class="button light" href="{{ url_for('students') }}">Clear search</a>{% endif %}</form>
            <div class="card"><table><thead><tr>
            <th>Admission No.</th><th>Student</th><th>Class</th><th>Date of birth</th><th>Parent</th><th>Phone</th><th>Status</th><th>Registered on</th><th>Actions</th></tr></thead><tbody>{% for student in rows %}<tr><td>{{ student['admission_no'] }}</td><td><b>{{ student['full_name'] }}</b><br>{{ student['gender'] or '' }}</td><td>{{ student['class_name'] or '-' }}</td><td>{{ student['date_of_birth'] or '-' }}</td><td>{{ student['parent_name'] }}</td><td>{{ student['parent_phone'] }}</td><td>{{ student['status'] }}</td><td>{{ student['created_at'] }}</td><td><div class="actions"><a class="button light" href="{{ url_for('student_edit', student_id=student['id']) }}">Edit</a><form method="post" action="{{ url_for('student_delete', student_id=student['id']) }}"><button class="danger" onclick="return confirm('Delete this student?')">Delete</button></form></div></td></tr>{% else %}<tr><td colspan="9">No students found.</td></tr>{% endfor %}</tbody></table></div>
        """, "Students", "students", query=query, rows=rows)


@app.route("/classes")
@login_required
def classes():
    rows = get_db().execute(
        "SELECT admission_no, full_name, class_name FROM students ORDER BY class_name, full_name"
    ).fetchall()
    grouped_students = {class_name: [] for class_name in CLASS_NAMES}
    class_names_by_key = {class_name.casefold(): class_name for class_name in CLASS_NAMES}
    other_classes = {}
    unassigned_students = []
    for student in rows:
        class_name = (student["class_name"] or "").strip()
        if not class_name:
            unassigned_students.append(student)
            continue
        official_name = class_names_by_key.get(class_name.casefold())
        if official_name:
            grouped_students[official_name].append(student)
        else:
            other_classes.setdefault(class_name, []).append(student)
    class_groups = [(name, grouped_students[name]) for name in CLASS_NAMES]
    class_groups.extend(sorted(other_classes.items(), key=lambda group: group[0].casefold()))
    if unassigned_students:
        class_groups.append(("No class assigned", unassigned_students))
    return page("""
        <div class="topbar"><div><h1>Classes</h1><p class="muted">Students are grouped by their assigned class.</p></div><a class="button light" href="{{ url_for('students') }}">All students</a></div>
        {% for class_name, class_students in class_groups %}
        <section class="card" style="margin-bottom:18px;">
          <div class="topbar"><div><h2>{{ class_name }}</h2><p class="muted">{{ class_students|length }} student(s)</p></div></div>
          {% if class_students %}<ul>{% for student in class_students %}<li><strong>{{ student['full_name'] }}</strong> <span class="muted">({{ student['admission_no'] }})</span></li>{% endfor %}</ul>{% else %}<p class="muted">No students assigned to this class yet.</p>{% endif %}
        </section>
        {% else %}<div class="card">No students have been registered yet.</div>{% endfor %}
        """, "Classes", "classes", class_groups=class_groups)


STUDENT_FORM = """
<div class="topbar"><div><h1>{{ heading }}</h1><p class="muted">Fill in the required student information.</p></div><a class="button light" href="{{ url_for('students') }}">Back</a></div>
<div class="card"><form method="post"><div class="form-grid">
  <div class="field"><label>Admission number *</label><input name="admission_no" value="{{ student['admission_no'] if student else '' }}" required></div>
    <div class="field"><label>Full student name *</label><input name="full_name" value="{{ student['full_name'] if student else '' }}" required></div>
    <div class="field"><label>Gender</label><select name="gender"><option value="">Select</option><option value="Male" {{ 'selected' if student and student['gender']=='Male' else '' }}>Male</option><option value="Female" {{ 'selected' if student and student['gender']=='Female' else '' }}>Female</option></select></div>
    <div class="field"><label>Date of birth</label><input type="date" name="date_of_birth" value="{{ student['date_of_birth'] if student else '' }}"></div>
    <div class="field"><label>Class *</label><select name="class_name" required><option value="">Select class</option>{% if student and student['class_name'] and student['class_name'] not in class_names %}<option value="{{ student['class_name'] }}" selected>{{ student['class_name'] }} (existing)</option>{% endif %}{% for class_name in class_names %}<option value="{{ class_name }}" {{ 'selected' if student and student['class_name'] == class_name else '' }}>{{ class_name }}</option>{% endfor %}</select></div>
    <div class="field"><label>Parent or guardian name *</label><input name="parent_name" value="{{ student['parent_name'] if student else '' }}" required></div>
    <div class="field"><label>Parent or guardian phone *</label><input name="parent_phone" value="{{ student['parent_phone'] if student else '' }}" required></div>
    <div class="field"><label>Status</label><select name="status"><option value="active" {{ 'selected' if not student or student['status']=='active' else '' }}>Active</option><option value="inactive" {{ 'selected' if student and student['status']=='inactive' else '' }}>Inactive</option></select></div>
    <div class="field full"><label>Address / additional information</label><textarea name="address">{{ student['address'] if student else '' }}</textarea></div>
</div><br><button>Save record</button></form></div>
"""


def student_values():
    return tuple(request.form.get(key, "").strip() for key in ("admission_no", "full_name", "gender", "date_of_birth", "class_name", "parent_name", "parent_phone", "address", "status"))


@app.route("/students/new", methods=("GET", "POST"))
@login_required
def student_new():
    if request.method == "POST":
        try:
            get_db().execute("INSERT INTO students (admission_no, full_name, gender, date_of_birth, class_name, parent_name, parent_phone, address, status) VALUES (?,?,?,?,?,?,?,?,?)", student_values())
            get_db().commit()
            flash("The student record was saved.")
            return redirect(url_for("students"))
        except sqlite3.IntegrityError:
            flash("That admission number is already in use.", "error")
    return page(STUDENT_FORM, "New student", "students", heading="Add new student", student=None, class_names=CLASS_NAMES)


@app.route("/students/<int:student_id>/edit", methods=("GET", "POST"))
@login_required
def student_edit(student_id):
    db = get_db()
    student = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        return "Student not found", 404
    if request.method == "POST":
        try:
            db.execute("UPDATE students SET admission_no=?, full_name=?, gender=?, date_of_birth=?, class_name=?, parent_name=?, parent_phone=?, address=?, status=? WHERE id=?", student_values() + (student_id,))
            db.commit()
            flash("The student record was updated.")
            return redirect(url_for("students"))
        except sqlite3.IntegrityError:
            flash("That admission number is already in use.", "error")
    return page(STUDENT_FORM, "Edit student", "students", heading="Edit student record", student=student, class_names=CLASS_NAMES)


@app.post("/students/<int:student_id>/delete")
@admin_required
def student_delete(student_id):
    get_db().execute("DELETE FROM students WHERE id = ?", (student_id,))
    get_db().commit()
    flash("The student record was deleted.")
    return redirect(url_for("students"))


@app.route("/announcements", methods=("GET", "POST"))
@login_required
def announcements():
    db = get_db()
    if request.method == "POST":
        title, body = request.form.get("title", "").strip(), request.form.get("body", "").strip()
        if title and body:
            db.execute("INSERT INTO announcements (title, body, author_id) VALUES (?,?,?)", (title, body, g.user["id"]))
            db.commit()
            flash("The announcement was published.")
            return redirect(url_for("announcements"))
        flash("Enter an announcement title and message.", "error")
    rows = db.execute("SELECT announcements.*, users.full_name AS author FROM announcements JOIN users ON users.id=announcements.author_id ORDER BY announcements.id DESC").fetchall()
    return page("""
            <div class="topbar"><div><h1>Announcements</h1><p class="muted">Share important updates with the school staff.</p></div></div>
            <div class="card"><h2>New announcement</h2><form method="post"><div class="form-grid"><div class="field"><label for="title">Title</label><input name="title" required></div><div class="field full"><label>Message</label><textarea name="body" required></textarea></div></div><br><button>Publish announcement</button></form></div><br>
            {% for item in rows %}<div class="card announcement"><h2>{{ item['title'] }}</h2><p>{{ item['body'] }}</p><small class="muted">{{ item['author'] }} | {{ item['created_at'] }}</small></div>{% else %}<div class="card">No announcements.</div>{% endfor %}
        """, "Announcements", "announcements")


@app.route("/users", methods=("GET", "POST"))
@admin_required
def users():
    db = get_db()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        phone = request.form.get("phone", "").strip()
        school_position = request.form.get("school_position", "").strip()
        homeroom_class = request.form.get("homeroom_class", "").strip()
        if homeroom_class not in CLASS_NAMES:
            homeroom_class = ""
        teaching_classes = [
            value for value in request.form.getlist("teaching_classes")
            if value in CLASS_NAMES
        ]
        subjects = [
            value for value in request.form.getlist("subjects")
            if value in SUBJECTS
        ]
        weekdays = [
            value for value in request.form.getlist("weekdays")
            if value in WEEKDAYS
        ]
        role = request.form.get("role", "staff")
        if role not in ("staff", "admin"):
            role = "staff"

        if not all((full_name, username, password, phone, school_position)):
            flash("Enter the staff member's required details.", "error")
        else:
            try:
                db.execute(
                    """INSERT INTO users
                       (full_name, username, password_hash, role, phone,
                        school_position, homeroom_class, teaching_classes, subjects, weekdays)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        full_name,
                        username,
                        generate_password_hash(password),
                        role,
                        phone,
                        school_position,
                        homeroom_class or None,
                        json.dumps(teaching_classes),
                        json.dumps(subjects),
                        json.dumps(weekdays),
                    ),
                )
                db.commit()
                flash("The new staff member was added.")
            except Exception as error:
                db.rollback()
                if isinstance(error, sqlite3.IntegrityError) or error.__class__.__name__ == "UniqueViolation":
                    flash("That username is already in use.", "error")
                    else:
        rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return page("""
    <div class="topbar"><div><h1>Staff & Admin</h1><p class="muted">Create staff sign-in profiles</p></div></div>
    <div class="card"><h2>Register staff member</h2><form method="post"><div class="grid">
    <div class="field"><label>Full name</label><input name="full_name" required></div>
    <div class="field"><label>Phone number</label><input name="phone" type="tel" required></div>
    <div class="field"><label>Position at school</label><input name="school_position" required></div>
    <div class="field"><label>Class assigned to the teacher (optional)</label><select name="homeroom_class"><option value="">None</option>{% for c in class_names %}<option value="{{ c }}">{{ c }}</option>{% endfor %}</select></div>
    <div class="field"><label>Username</label><input name="username" required></div>
    <div class="field"><label>Temporary password</label><input type="password" name="password" required></div>
    <div class="field"><label>App access permission</label><select name="role"><option value="staff">Staff</option><option value="admin">Admin</option></select></div>
    <fieldset class="choice-panel full"><legend>Classes taught</legend><div class="choice-grid">{% for c in class_names %}<label><input type="checkbox" name="teaching_classes" value="{{ c }}"> {{ c }}</label>{% endfor %}</div></fieldset>
    <fieldset class="choice-panel full"><legend>Subjects taught</legend><div class="choice-grid">{% for s in subjects %}<label><input type="checkbox" name="subjects" value="{{ s }}"> {{ s }}</label>{% endfor %}</div></fieldset>
    <fieldset class="choice-panel full"><legend>Teaching days (Asabar to Laraba)</legend><div class="choice-grid">{% for d in ['Asabar','Lahadi','Litinin','Talata','Laraba'] %}<label><input type="checkbox" name="weekdays" value="{{ d }}"> {{ d }}</label>{% endfor %}</div></fieldset>
    </div><br><button>Save staff member</button></form></div>
    <div class="card"><h2>Accounts</h2><table><thead><tr><th>Full name</th><th>Phone</th><th>Username</th><th>Role</th></tr></thead><tbody>{% for r in rows %}<tr><td>{{ r['full_name'] }}</td><td>{{ r['phone'] }}</td><td>{{ r['username'] }}</td><td>{{ r['role'] }}</td></tr>{% endfor %}</tbody></table></div>
    """, "Staff & Admin", "users", rows=rows, class_names=CLASS_NAMES, subjects=SUBJECTS)

@app.route("/staff")
@login_required
def staff_directory():
    rows = get_db().execute(
        """SELECT full_name, phone, school_position, homeroom_class,
                  teaching_classes, subjects, weekdays
           FROM users WHERE role = ? ORDER BY full_name""",
        ('staff',),
    ).fetchall()
    staff_members = []
    for row in rows:
        staff_members.append({
            "full_name": row["full_name"],
            "phone": row["phone"],
            "school_position": row["school_position"],
            "homeroom_class": row["homeroom_class"],
            "teaching_classes": json.loads(row["teaching_classes"] or '[]'),
            "subjects": json.loads(row["subjects"] or '[]'),
            "weekdays": json.loads(row["weekdays"] or '[]'),
        })
    return page("""
    <div class="topbar"><div><h1>Staff directory</h1><p class="muted">Staff contact and teaching info</p></div></div>
    <div class="grid">{% for member in staff_members %}<article class="card">
    <h2>{{ member['full_name'] }}</h2>
    <p><strong>Phone:</strong> {% if member['phone'] %}<a href="tel:{{ member['phone'] }}">{{ member['phone'] }}</a>{% else %} - {% endif %}</p>
    <p><strong>Position:</strong> {{ member['school_position'] or ' - ' }}</p>
    <p><strong>Assigned Class:</strong> {{ member['homeroom_class'] or 'None' }}</p>
    <p><strong>Classes taught:</strong> {{ member['teaching_classes']|join(', ') or 'None' }}</p>
    <p><strong>Subjects:</strong> {{ member['subjects']|join(', ') or 'None listed' }}</p>
    <p><strong>Days:</strong> {{ member['weekdays']|join(', ') or 'None listed' }}</p>
    </article>{% else %}<div class="card">No staff profiles have been registered yet.</div>{% endfor %}</div>
    """, "Staff directory", "staff", staff_members=staff_members)


if __name__ == "__main__":
    app.run(debug=True)
