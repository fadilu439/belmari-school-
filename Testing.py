import os
import json
import sqlite3
import calendar
from datetime import date, datetime, timedelta
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

    # New collaboration tables; existing school data and tables are preserved.
    if use_postgres():
        db.execute("""CREATE TABLE IF NOT EXISTS offices (
            id SERIAL PRIMARY KEY, office_name TEXT UNIQUE NOT NULL,
            leader TEXT NOT NULL DEFAULT 'To be assigned',
            members TEXT NOT NULL DEFAULT 'To be assigned', duties TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS workplace_messages (
            id SERIAL PRIMARY KEY, sender_id INTEGER NOT NULL REFERENCES users(id),
            message TEXT NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT,
            assigned_to INTEGER REFERENCES users(id), due_date TEXT,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
    else:
        db.execute("""CREATE TABLE IF NOT EXISTS offices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, office_name TEXT UNIQUE NOT NULL,
            leader TEXT NOT NULL DEFAULT 'To be assigned',
            members TEXT NOT NULL DEFAULT 'To be assigned', duties TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS workplace_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id INTEGER NOT NULL,
            message TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sender_id) REFERENCES users(id)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT,
            assigned_to INTEGER, due_date TEXT, status TEXT NOT NULL DEFAULT 'Pending',
            created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(assigned_to) REFERENCES users(id),
            FOREIGN KEY(created_by) REFERENCES users(id)
        )""")

    # School calendar is additive: it does not alter existing school tables.
    if use_postgres():
        db.execute("""CREATE TABLE IF NOT EXISTS school_events (
            id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_date TEXT NOT NULL,
            end_date TEXT, event_type TEXT NOT NULL DEFAULT 'General', description TEXT
        )""")
    else:
        db.execute("""CREATE TABLE IF NOT EXISTS school_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, event_date TEXT NOT NULL,
            end_date TEXT, event_type TEXT NOT NULL DEFAULT 'General', description TEXT
        )""")

    default_school_events = (
        ("Dawowa Makaranta", "2026-09-05", "2026-09-05", "Term Opening", "Asabar - Dawowa Makaranta"),
        ("Assembly", "2026-09-06", "2026-09-06", "Assembly", "Lahadi - Assembly"),
        ("Cigaba da karatu", "2026-09-13", "2026-09-13", "Academic", "Lahadi - Cigaba da karatu"),
        ("Lecture", "2026-10-25", "2026-10-25", "Academic", "Lahadi - Lecture"),
        ("Cigaba da karatu", "2026-10-31", "2026-10-31", "Academic", "Asabar - Cigaba da karatu"),
        ("Lecture", "2026-12-06", "2026-12-06", "Academic", "Lahadi - Lecture"),
        ("Revision", "2026-12-12", "2026-12-16", "Revision", "Revision period"),
        ("Nishadat (Wasanni)", "2026-12-19", "2026-12-22", "Sports", "Nishadat (Wasanni)"),
        ("Rufe Makaranta / Walima", "2026-12-23", "2026-12-23", "School Closing", "Laraba - Rufe Makaranta / Walima"),
        ("Dawowa Makaranta (New Term)", "2027-01-02", "2027-01-02", "Term Opening", "Asabar - Dawowa Makaranta (New Term)"),
    )# NEW TABLES - English Only
if use_postgres():
    db.execute("""CREATE TABLE IF NOT EXISTS exam_results (
        id SERIAL PRIMARY KEY,
        student_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        exam_type TEXT NOT NULL,
        score REAL NOT NULL,
        total REAL NOT NULL DEFAULT 100,
        exam_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_channels (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id SERIAL PRIMARY KEY,
        channel_id INTEGER,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS office_records (
        id SERIAL PRIMARY KEY,
        office_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        record_date TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
else:
    db.execute("""CREATE TABLE IF NOT EXISTS exam_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        subject TEXT NOT NULL,
        exam_type TEXT NOT NULL,
        score REAL NOT NULL,
        total REAL NOT NULL DEFAULT 100,
        exam_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_channels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_id INTEGER,
        sender_id INTEGER NOT NULL,
        receiver_id INTEGER,
        message TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS office_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        office_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        record_date TEXT,
        created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    for event in default_school_events:
        exists = db.execute(
            "SELECT id FROM school_events WHERE title=? AND event_date=? AND end_date=?",
            (event[0], event[1], event[2]),
        ).fetchone()
        if exists is None:
            db.execute(
                "INSERT INTO school_events (title, event_date, end_date, event_type, description) VALUES (?, ?, ?, ?, ?)",
                event,
            )

    # Remove only legacy built-in office names before seeding the school's
    # definitive eight departments. Custom office records are left untouched.
    previous_default_offices = (
        "Administration Office",
        "Academic Affairs Office",
        "Qur'an & Islamic Studies Office",
        "Student Affairs Office",
        "Finance & Accounts Office",
        "Staff Affairs Office",
        "Welfare & Guidance Office",
        "ICT & Communications Office",
        "Admissions & Records Office",
        "Examination Office",
        "Public Relations Office (P.R.O)",
        "Health Office",
        "Custodian & School Property Office",
        "Competition & Visits Office",
        "Timetable & Curriculum Office",
    )
    placeholders = ",".join(["?"] * len(previous_default_offices))
    db.execute(
        f"DELETE FROM offices WHERE office_name IN ({placeholders})",
        previous_default_offices,
    )

    default_offices = (
        (
            "Mai Kula da Harkar Jarrabawa (Examination Office)",
            "M. Yahya Dahiru",
            "M. Aliyu Abdullahi, M. Ismail Husaini, M. Shamsu Adam, M. Abdussamad Sunusi, M. Saifullahi Haruna",
            "\n".join([
                "Tattara manhaja (syllabus) daga kowane malami kafin a shirya tambayoyi",
                "Raba format (yadda questions za su kasance) na tambayoyi ga malaman",
                "Karɓar tambayoyi da gyara su (moderation) da tabbatar da sun dace da ajin",
                "Buga tambayoyi da kiyaye sirri 100%",
                "Tsara jadawalin jarabawa (Exam Time Table)",
                "Tsara wurin zama (Seating Arrangement) na dalibai",
                "Shirya takardun amsa (Answer Sheets) da suka isa",
                "Raba masu tsaron jarabawa (Invigilators) kowace rana",
                "Buɗe tambayoyi a ɗakin jarrabawa a gaban dalibai",
                "Ɗaukar attendance na daliban da suka shiga jarabawa",
                "Tattarawa da ƙirga dukkan Scripts bayan kowace jarabawa",
                "Raba Scripts ga malaman don marking da bibiyar su har su dawo (da su)",
                "Karɓar sakamako, shigar da shi a Broadsheet / Computer",
                "Bincika sakamako da fitar da Report Sheet",
                "Kiyaye tsofaffin sakamako a file na sirri",
                "Rubuta rahoton duk wani magudi (Malpractice) da aka samu",
            ]),
        ),
        (
            "Mai Kula da Harkokin Dalibai (Student Affairs Office)",
            "M. Sadik Inuwa",
            "M. Shamsu Adam",
            "\n".join([
                "Kula da ladabi, halaye, da mutunci na dalibai",
                "Tabbatar da kowa na sanya uniform na makaranta yadda ya kamata",
                "Kula da attendance na yau da kullum: waye ya zo, waye bai zo ba",
                "Karɓar korafe-korafe da warware rikici tsakanin dalibai",
                "Ba da gargadi da horo ga daliban da suka karya doka",
                "Kula da lokacin shigowa da fita makaranta",
                "Tura rahoton dalibai masu yawan laifi zuwa Management",
            ]),
        ),
        (
            "Magatakarda da Mai Ɗaukar Dalibai (Admissions & Registrar Office)",
            "M. Saifullahi Haruna",
            "Ml. Hafsa Auwal",
            "\n".join([
                "Bayarwa da karɓar Admission Forms",
                "Yi wa sabbin dalibai interview da tantancewa",
                "Yi musu registration da ba su lambar makaranta (Admission No.)",
                "Buɗe file ga kowane dalibi da kiyaye takardunsa (hoto, birth certificate)",
                "Kula da Register kuɗin makaranta tare da Finance",
                "Tura cikakken jerin sunayen sabbin dalibai zuwa Office Jarrabawa / Office Timetable da manhaji",
                "Kula da daliban da suka bar makaranta (Transfer) da bayar da takarda",
                "Kiyaye babban littafin ɗaukar dalibai (Admission Register)",
            ]),
        ),
        (
            "Jami’in Hulɗa da Jama’a (P.R.O)",
            "Ml. Khadija Hassan",
            "M. Muhammad Aliyu",
            "\n".join([
                "Karɓar duk wani bako da ya ziyarci makaranta da girmamawa",
                "Zama mai magana da yawun makaranta a waje",
                "Hulɗa da iyayen dalibai: kira da sanarwa",
                "Rubuta dukkan sanarwa (Announcements) da gayyata (Invitations)",
                "Hulɗa da ƙungiyar SABOSA (Tsofaffin Dalibai)",
                "Shirya ranakun walima, yaye dalibai, da tarurruka na musamman",
            ]),
        ),
        (
            "Mai Kula da Rashin Lafiyar Dalibai (Health Office)",
            "Ml. Maryam Sulaiman",
            "Not specified",
            "\n".join([
                "Kula da daliban da ba su da lafiya a cikin makaranta",
                "Kula da First Aid Box - tabbatar da magunguna na ciki",
                "Kula da tsaftar bandaki, ruwan sha, da wajen wanke hannu",
                "Kira ga iyaye idan dalibi ya yi rashin lafiya mai tsanani",
                "Ba da shawara kan tsaftar jiki da muhalli ga dalibai mata",
                "Rubuta sunayen daliban da suka yi rashin lafiya da rana",
                "Tabbatar da ajujuwa na da iska da tsafta domin hana yaɗuwar cuta",
            ]),
        ),
        (
            "Mai Kula da Tsaftar Makaranta da Kayan Makaranta (Custodian Office)",
            "M. Saifullahi Haruna",
            "Ml. Hafsa Auwal, Ml. Asama'u Hassan, M. Abdussamad Sunusi, M. Muhammad Aliyu, Ml. Salama Yahuza, Ml. Halima Aliyu",
            "\n".join([
                "Tsara jadawalin tsaftace ajujuwa da harabar makaranta kowace rana",
                "Kula da tabarmi, kujeru, allo, ƙofofi, da tagogi - idan sun lalace a kai rahoto",
                "Kula da buɗewa da rufe makaranta akan lokaci",
                "Kula da wutar lantarki, fanfo, da fitilu",
                "Raba Marker / alli, goge allo, da kayan aiki ga malaman",
                "Kula da kayan makaranta a store - shiga da fita",
                "Tabbatar da babu datti a bayan aji da cikin bandaki",
            ]),
        ),
        (
            "Tsara Musabaka da Ziyarta (Competition & Visits Office)",
            "M. Shamsu Adam",
            "M. Ismail Husaini, Ml. Salama Yahuza, Ml. Hauwa'u Sa'id",
            "\n".join([
                "Tsara musabaka na ciki tsakanin ajujuwa",
                "Zaɓar daliban da za su wakilci makaranta a musabakar waje",
                "Horar da daliban da za su yi gasa na musamman",
                "Tsarawa da shirya ziyarce-ziyarce zuwa wasu makarantu ko wurare masu amfani",
                "Rubuta wasiku na neman izinin ziyara",
                "Kula da kyaututtuka, certificate, da kayan musabaka",
                "Rubuta rahoton kowace musabaka da ziyara da aka yi",
            ]),
        ),
        (
            "Tsara Time Table da Manhaja (Curriculum Office)",
            "M. Aliyu Abdullahi",
            "M. Sadik Inuwa, M. Shamsu Adam, M. Saifullahi Haruna, M. Abdussamad Sunusi, Ml. Hauwa'u Yusuf, Ml. Halima Aliyu, M. Yahya Dahiru",
            "\n".join([
                "Tsara babban Time Table na makaranta na kowace term",
                "Raba darussa ga malaman bisa ga ƙwarewa",
                "Tsara manhaja (Curriculum / Scheme of Work) ta kowane aji",
                "Tabbatar da kowane aji na da malami a kowane lokaci",
                "Canza time table na rana idan wani malami bai zo ba (Relief)",
                "Rubutawa da raba dukkan Circulars da dokoki ga malaman",
                "Kula da littafan koyarwa (Lesson Notes) na malaman - ana duba su?",
                "Bincikawa ko malaman na tafiya daidai da manhaja",
            ]),
        ),
    )

    # Update the previous abbreviated built-in descriptions once, while keeping
    # any later administrator-edited office records intact.
    old_duties = {
        "Examination Office": "Prepare and print exam questions, Prepare exam timetable, Assign invigilators, Collect answer scripts, Enter results and issue results, Keep exam questions confidential.",
        "Student Affairs Office": "Student discipline and character, Receive student complaints, Resolve disputes between students, Monitor student attendance, Ensure students wear correct school uniform.",
        "Admissions & Records Office": "Receive new students and register them, Keep student files and documents, Issue admission form and school fees list, Send names of new students to Examination Office.",
        "Public Relations Office (P.R.O)": "Receive visitors, Promote the school outside, Relate with parents, Write announcements and invitations.",
        "Health Office": "Care for sick students, Manage first aid box, Inform parents if illness is serious, Care for toilet and drinking water cleanliness, Advise on environmental cleanliness.",
        "Custodian & School Property Office": "Cleanliness of classes and school compound, Care for mats, chairs, boards and class materials, Open and close school, Care for electricity and water, Distribute working materials to teachers.",
        "Competition & Visits Office": "Organize competitions inside school, Prepare students for inter-school competitions, Organize visits to other schools, Train competing students, Manage competition prizes.",
        "Timetable & Curriculum Office": "Prepare daily timetable, Prepare curriculum for each class, Write and distribute circulars to teachers, Change timetable if a teacher is absent, Ensure every class has a teacher on time.",
    }
    for office_name, leader, members, duties in default_offices:
        existing = db.execute("SELECT id, duties FROM offices WHERE office_name=?", (office_name,)).fetchone()
        if existing is None:
            if use_postgres():
                db.execute(
                    "INSERT INTO offices (office_name, leader, members, duties) VALUES (%s, %s, %s, %s) ON CONFLICT (office_name) DO NOTHING",
                    (office_name, leader, members, duties),
                )
            else:
                db.execute(
                    "INSERT OR IGNORE INTO offices (office_name, leader, members, duties) VALUES (?, ?, ?, ?)",
                    (office_name, leader, members, duties),
                )
        elif existing["duties"] == old_duties.get(office_name):
            db.execute(
                "UPDATE offices SET leader=?, members=?, duties=? WHERE id=?",
                (leader, members, duties, existing["id"]),
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
        admin = db.execute("SELECT id FROM users WHERE username =?", ("admin",)).fetchone()
        if admin is None:
            db.execute(
                "INSERT INTO users (full_name, username, password_hash, role) VALUES (?,?,?,?)",
                ("Main Administrator", "admin", generate_password_hash("admin123"), "admin"),
            )
    db.commit()

@app.before_request
def prepare_request():
    init_db()
    g.user = None
    if session.get("user_id"):
        g.user = get_db().execute(
            "SELECT * FROM users WHERE id =?", (session["user_id"],)
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
        if g.user["role"]!= "admin":
            flash("This section is for the main administrator only.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped_view

BASE_HTML = """
<!doctype html>
<html lang="en" dir="ltr">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{{ title }} | MADRASATU BELMARI QUR'ANIC SCHOOL</title>
  <style>
    :root {
      --bg: #f0f7ff;
      --paper: #ffffff;
      --ink: #0f2440;
      --muted: #6b84a3;
      --primary: #0b3fa6;
      --primary-dark: #082d77;
      --primary-soft: #e6f0ff;
      --accent: #3b82f6;
      --accent-soft: #dbeafe;
      --border: #dbe7fb;
      --sidebar: #071e42;
      --sidebar-soft: #0f3a84;
      --success-bg: #e8f5ff;
      --error-bg: #ffea;
      --shadow: 0 14px 36px rgba(11, 63, 166, 0.14);
      --shadow-soft: 0 8px 22px rgba(11, 63, 166, 0.10);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: linear-gradient(180deg, #f7fbff 0%, #eef6ff 100%);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.5;
    }
    a { color: inherit; text-decoration: none; }
   .layout { min-height:100vh; display:flex; }
    aside {
      width: 270px;
      background: linear-gradient(180deg, var(--sidebar) 0%, var(--sidebar-soft) 100%);
      color: #edf5ff;
      padding: 28px 18px;
      flex-shrink: 0;
      box-shadow: 4px 0 24px rgba(7, 30, 66, 0.18);
    }
   .brand-wrap {
      display:flex;
      align-items:center;
      gap:12px;
      padding: 8px 4px 18px;
      margin-bottom: 20px;
      border-bottom: 1px solid rgba(255,255,255,0.14);
    }
   .brand-mark {
      width: 54px;
      height: 54px;
      border-radius: 16px;
      background: linear-gradient(135deg, #ffffff 0%, #b8d4ff 100%);
      color: var(--primary-dark);
      display:grid;
      place-items:center;
      font-weight: 900;
      font-size: 24px;
      box-shadow: 0 6px 18px rgba(0,0,0,0.18), inset 0 0 0 3px rgba(255,255,255,0.7);
    }
   .brand {
      font-size: 14px;
      font-weight: 800;
      line-height: 1.25;
      color: #f4f8ff;
      letter-spacing: 0.3px;
    }
   .welcome {
      color: #cfe0ff;
      font-size: 14px;
      margin: 0 0 18px;
    }
    nav a {
      display:block;
      padding: 13px 14px;
      border-radius: 12px;
      margin: 6px 0;
      color: #d9e9ff;
      transition: all 0.2s ease;
      font-weight: 600;
      border: 1px solid transparent;
    }
    nav a:hover, nav a.active {
      background: rgba(255,255,255,0.12);
      color: #ffffff;
      border-color: rgba(255,255,255,0.18);
      box-shadow: var(--shadow-soft);
      transform: translateX(2px);
    }
    main {
      flex: 1;
      padding: 32px;
      max-width: 1500px;
    }
   .topbar {
      display:flex;
      justify-content:space-between;
      gap:16px;
      align-items:center;
      margin-bottom:24px;
    }
    h1,h2,h3 { margin-top:0; }
    h1 { font-size: 30px; margin-bottom: 6px; color: var(--primary-dark); }
    h2 { font-size: 22px; color: var(--primary-dark); }
   .muted { color: var(--muted); }
   .grid {
      display:grid;
      grid-template-columns:repeat(4,1fr);
      gap:18px;
      margin-bottom:26px;
    }
   .card {
      background: var(--paper);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 22px;
      box-shadow: var(--shadow);
    }
   .stat { border-top: 4px solid var(--accent); }
   .stat strong {
      display:block;
      font-size: 32px;
      margin-top:10px;
      color: var(--primary);
    }
   .toolbar {
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      margin-bottom:18px;
    }
    input,select,textarea {
      width:100%;
      padding: 13px 14px;
      border: 1px solid var(--border);
      border-radius: 12px;
      background:#fff;
      font:inherit;
      color: var(--ink);
      box-shadow: 0 2px 8px rgba(11,63,166,0.04);
      transition: all 0.2s ease;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--primary);
      box-shadow: 0 0 0 4px rgba(59,130,246,0.15);
    }
    textarea { min-height: 120px; resize: vertical; }
   .search { flex:1; min-width:220px; }
    button,.button {
      border:0;
      border-radius: 12px;
      padding: 13px 20px;
      background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
      color:white;
      cursor:pointer;
      font:inherit;
      display:inline-block;
      font-weight: 700;
      box-shadow: 0 8px 18px rgba(11,63,166,0.22);
      transition: all 0.2s ease;
    }
    button:hover,.button:hover { transform: translateY(-1px); box-shadow: 0 12px 24px rgba(11,63,166,0.28); }
   .button.gold { background: #aa7b1d; }
   .button.light { background:#ffffff; color: var(--primary-dark); border:1px solid var(--border); box-shadow: var(--shadow-soft); }
   .button.danger { background: #b5473a; }
    table { width:100%; border-collapse: collapse; background: white; border-radius: 12px; overflow:hidden; }
    th,td { padding: 13px 12px; border-bottom:1px solid var(--border); text-align:left; vertical-align:top; }
    th { background:#f0f6ff; color: var(--primary-dark); font-weight:800; }
   .form-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:16px; }
   .choice-panel { border:1px solid var(--border); border-radius:14px; padding:16px; background: #fbfdff; box-shadow: inset 0 1px 0 rgba(255,255,255,0.8); }
   .choice-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:8px 14px; }
   .choice-option { display:flex!important; align-items:center; gap:8px; margin:0; font-weight:500!important; }
   .choice-option input[type="checkbox"] { width:18px; height:18px; margin:0; padding:0; }
   .field label { display:block; font-weight:700; margin-bottom:6px; color: var(--primary-dark); }
   .full { grid-column:1/-1; }
   .flash { padding:14px 16px; border-radius:12px; background: var(--success-bg); margin-bottom:16px; color: #0f3d62; border:1px solid var(--border); box-shadow: var(--shadow-soft); }
   .flash.error { background: var(--error-bg); color: #7c2a2a; }
   .login-page {
      min-height:100vh;
      display:grid;
      place-items:center;
      padding:20px;
      background: radial-gradient(1200px 600px at 20% -10%, #2a5ec8 0%, transparent 60%), radial-gradient(1000px 500px at 90% 110%, #3b82f6 0%, transparent 60%), linear-gradient(135deg, #071e42 0%, #0f3a84 45%, #1a5bd6 100%);
    }
   .login-box {
      width:min(480px, 100%);
      background: rgba(255,255,255,0.98);
      padding: 36px 32px;
      border-radius: 24px;
      box-shadow: 0 24px 60px rgba(7, 30, 66, 0.28), 0 8px 20px rgba(7, 30, 66, 0.18);
      border: 1px solid rgba(255,255,255,0.6);
      backdrop-filter: blur(6px);
    }
   .login-box h1 { color: var(--primary); }
   .login-logo {
      display:flex;
      align-items:center;
      gap:14px;
      margin-bottom: 18px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }
   .login-mark {
      width: 62px;
      height: 62px;
      border-radius: 18px;
      background: linear-gradient(135deg, #ffffff 0%, #a9c8ff 100%);
      color: var(--primary-dark);
      display:grid;
      place-items:center;
      font-weight: 900;
      font-size: 28px;
      box-shadow: 0 8px 20px rgba(11,63,166,0.18), inset 0 0 0 3px rgba(255,255,255,0.7);
    }
   .announcement {
      border-left: 4px solid var(--accent);
      margin-bottom: 14px;
      background: #ffffff;
      box-shadow: var(--shadow-soft);
    }
   .actions { display:flex; gap:6px; flex-wrap:wrap; }
   .school-name {
      font-size: 28px;
      font-weight: 800;
      color: var(--primary-dark);
      margin-bottom: 8px;
    }
   .brand-subtitle {
      color: var(--muted);
      font-size: 14px;
      margin-bottom: 18px;
    }
    .calendar-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; margin-bottom:18px; }
    .calendar-grid { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:7px; }
    .calendar-weekday { text-align:center; font-weight:800; color:var(--primary-dark); padding:10px 3px; background:#edf4ff; border-radius:10px; font-size:13px; }
    .calendar-day { min-height:118px; padding:9px; border:1px solid var(--border); border-radius:12px; background:#fff; overflow-wrap:anywhere; }
    .calendar-day.empty { background:transparent; border:1px dashed #dce7f7; }
    .calendar-day.today { border:2px solid #2563eb; background:#e8f1ff; box-shadow:0 0 0 2px rgba(37,99,235,.08); }
    .calendar-day.closed { background:#fff0f0; border-color:#efaaaa; }
    .calendar-day.school-day { border-top:3px solid #3b82f6; }
    .day-number { font-weight:900; color:var(--primary-dark); display:flex; justify-content:space-between; gap:4px; }
    .today-label { color:#1d4ed8; font-size:10px; font-weight:800; }
    .closed-label { color:#b42318; font-size:10px; font-weight:800; }
    .calendar-event { display:block; margin-top:6px; padding:5px 6px; border-radius:7px; background:#eaf2ff; color:#123b82; font-size:11px; line-height:1.3; }
    .calendar-event.range { background:#f0eaff; color:#56358b; }
    .calendar-legend { display:flex; flex-wrap:wrap; gap:12px; margin:14px 0; color:var(--muted); font-size:13px; }
    .legend-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:5px; }
    .event-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    @media(max-width:700px) { .calendar-day { min-height:92px; padding:5px; font-size:12px; } .calendar-weekday { font-size:10px; padding:7px 1px; } .calendar-event { font-size:9px; padding:4px; } .event-form { grid-template-columns:1fr; } }
    .office-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:18px; }
    .office-card { border-top:4px solid var(--accent); }
    .office-card h2 { margin-bottom:14px; }
    .office-duties { margin-top:14px; }
    .office-duties ol { margin:10px 0 0; padding-left:24px; }
    .office-duties li { margin:0 0 9px; line-height:1.65; padding-left:3px; }
    .chat-window { max-height:520px; overflow-y:auto; display:flex; flex-direction:column; gap:12px; }
    .chat-message { padding:13px 16px; border:1px solid var(--border); border-radius:14px; background:#f8fbff; }
    .chat-message.mine { background:var(--primary-soft); border-color:#b8d1fa; }
    .chat-meta { display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--muted); margin-bottom:5px; }
    .task-status { display:inline-block; padding:5px 10px; border-radius:20px; background:var(--primary-soft); color:var(--primary-dark); font-size:12px; font-weight:700; }
    .task-status.done { background:#e6f7ed; color:#17663a; }
    .task-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
    @media(max-width:620px) { .task-form { grid-template-columns:1fr; } }
    @media(max-width:900px) { aside { width:210px; }.grid { grid-template-columns:repeat(2,1fr); } main { padding:20px; } }
    @media(max-width:620px) {.layout { display:block; } aside { width:100%; padding:12px; } nav { display:flex; overflow:auto; gap:4px; } nav a { white-space:nowrap; }.grid,.form-grid { grid-template-columns:1fr; } main { padding:15px; }.topbar { align-items:flex-start; flex-direction:column; } table { min-width:850px; } }
  </style>
</head>
<body>
{% if g.user %}<div class="layout"><aside><div class="brand-wrap"><div class="brand-mark">Q</div><div class="brand">MADRASATU BELMARI<br>QUR'ANIC SCHOOL</div></div><div class="welcome">Welcome, {{ g.user['full_name'] }}</div><nav>
  <a href="{{ url_for('dashboard') }}" class="{{ 'active' if page == 'dashboard' else '' }}">Dashboard</a>
    <a href="{{ url_for('students') }}" class="{{ 'active' if page == 'students' else '' }}">Students</a>
        <a href="{{ url_for('classes') }}" class="{{ 'active' if page == 'classes' else '' }}">Classes</a>
    <a href="{{ url_for('staff_directory') }}" class="{{ 'active' if page == 'staff' else '' }}">Staff directory</a>
    <a href="{{ url_for('announcements') }}" class="{{ 'active' if page == 'announcements' else '' }}">Announcements</a>
    <a href="{{ url_for('school_calendar') }}" class="{{ 'active' if page == 'school_calendar' else '' }}">School Calendar</a>
    {% if g.user['role'] == 'admin' %}<a href="{{ url_for('users') }}" class="{{ 'active' if page == 'users' else '' }}">Staff &amp; Admin</a>{% endif %}
    <a href="{{ url_for('offices') }}" class="{{ 'active' if page == 'offices' else '' }}">Offices</a>
    <a href="{{ url_for('workplace_chat') }}" class="{{ 'active' if page == 'workplace_chat' else '' }}">Workplace Chat</a>
    <a href="{{ url_for('tasks') }}" class="{{ 'active' if page == 'tasks' else '' }}">Tasks</a>
    <a href="{{ url_for('logout') }}">Log out</a>
</nav></aside><main>
{% else %}<div class="login-page"><div class="login-box">{% endif %}
{% with messages = get_flashed_messages(with_categories=true) %}{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}{% endwith %}
{{ content|safe }}
{% if g.user %}</main></div>{% else %}</div></div>{% endif %}
</body></html>
"""

def page(content, title, page_name, **context):
    rendered_content = render_template_string(content, **context)
    return render_template_string(BASE_HTML, content=rendered_content, title=title, page=page_name)

@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = get_db().execute("SELECT * FROM users WHERE username =?", (request.form["username"].strip(),)).fetchone()
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
    <div class="brand-subtitle" style="margin-top:-4px;">Secure staff portal</div>
    <form method="post">
      <div class="field"><label>Username</label><input name="username" required autofocus></div><br>
      <div class="field"><label>Password</label><input type="password" name="password" required></div><br>
      <button>Log in</button>
    </form>
    <p class="muted" style="margin-top:18px;">Please sign in with your staff credentials to continue.</p>
    """, "Log in", "login")

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
    walima_date = date(2026, 12, 23)
    walima_days = (walima_date - date.today()).days
    return page("""
    <div class="topbar"><div><h1>Dashboard</h1><p class="muted">School performance overview</p></div><a class="button" href="{{ url_for('student_new') }}">+ Add student</a></div>
    <div class="grid">{% for label, value in [('Active students', stats.students), ('Staff members', stats.staff), ('Announcements', stats.announcements), ('New students (30 days)', stats.new_students)] %}<div class="card stat"><span class="muted">{{ label }}</span><strong>{{ value }}</strong></div>{% endfor %}</div>
    <div class="card" style="margin-bottom:24px; border-left:5px solid #2563eb;"><span class="muted">Countdown to Walima / Rufe Makaranta</span><div style="font-size:30px;font-weight:900;color:#0b3fa6;margin-top:5px;">{% if walima_days > 0 %}{{ walima_days }} days remaining{% elif walima_days == 0 %}Today is Walima{% else %}Walima date has passed{% endif %}</div><p class="muted" style="margin-bottom:0;">Wednesday, 23 December 2026</p><a class="button light" style="margin-top:12px;" href="{{ url_for('school_calendar', year=2026, month=12) }}">Open School Calendar</a></div>
    <a class="card" href="{{ url_for('classes') }}" style="display:block; margin-bottom:24px;"><h2>Classes and student lists</h2><p class="muted">Browse students grouped by class.</p><span class="button">View classes</span></a>
    <a class="card" href="{{ url_for('staff_directory') }}" style="display:block; margin-bottom:24px;"><h2>Staff directory</h2><p class="muted">View staff contact, role, classes, subjects, and days.</p><span class="button">View staff</span></a>
    <div class="card"><h2>Latest announcements</h2>{% for item in latest %}<div class="announcement"><h3>{{ item['title'] }}</h3><p>{{ item['body'] }}</p><small class="muted">{{ item['created_at'] }}</small></div>{% else %}<p class="muted">No announcements yet.</p>{% endfor %}</div>
    """, "Dashboard", "dashboard", stats=stats, latest=latest, walima_days=walima_days)

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
    student = db.execute("SELECT * FROM students WHERE id =?", (student_id,)).fetchone()
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
    get_db().execute("DELETE FROM students WHERE id =?", (student_id,))
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
        """, "Announcements", "announcements", rows=rows)

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
                    raise
    rows = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    return page("""
        <div class="topbar"><div><h1>Staff &amp; Admin</h1><p class="muted">Create staff sign-in accounts and maintain their school profiles.</p></div><a class="button light" href="{{ url_for('staff_directory') }}">Staff directory</a></div>
        <div class="card"><h2>Register staff member</h2><form method="post"><div class="form-grid">
          <div class="field"><label>Full name *</label><input name="full_name" required></div>
          <div class="field"><label>Phone number *</label><input name="phone" type="tel" required></div>
          <div class="field"><label>Position at school *</label><input name="school_position" placeholder="For example: Qur'an teacher" required></div>
          <div class="field"><label>Class assigned to the teacher (optional)</label><select name="homeroom_class"><option value="">No assigned class</option>{% for class_name in class_names %}<option value="{{ class_name }}">{{ class_name }}</option>{% endfor %}</select></div>
          <div class="field"><label>Username *</label><input name="username" required></div>
          <div class="field"><label>Temporary password *</label><input type="password" name="password" minlength="6" required></div>
          <div class="field"><label>App access permission</label><select name="role"><option value="staff">Staff</option><option value="admin">Admin</option></select></div>
          <fieldset class="choice-panel full"><legend>Classes taught</legend><div class="choice-grid">{% for class_name in class_names %}<label class="choice-option"><input type="checkbox" name="teaching_classes" value="{{ class_name }}">{{ class_name }}</label>{% endfor %}</div></fieldset>
          <fieldset class="choice-panel full"><legend>Subjects taught</legend><div class="choice-grid">{% for subject in subjects %}<label class="choice-option"><input type="checkbox" name="subjects" value="{{ subject }}">{{ subject }}</label>{% endfor %}</div></fieldset>
          <fieldset class="choice-panel full"><legend>Teaching days (Asabar to Laraba)</legend><div class="choice-grid">{% for weekday in weekdays %}<label class="choice-option"><input type="checkbox" name="weekdays" value="{{ weekday }}">{{ weekday }}</label>{% endfor %}</div></fieldset>
        </div><br><button>Save staff member</button></form></div><br>
        <div class="card"><h2>Accounts</h2><table><thead><tr><th>Full name</th><th>Phone</th><th>School position</th><th>Access</th><th>Actions</th></tr></thead><tbody>{% for user in rows %}<tr><td>{{ user['full_name'] }}</td><td>{{ user['phone'] or '-' }}</td><td>{{ user['school_position'] or '-' }}</td><td>{{ user['role'] }}<td>{{ user['created_at'] }}</td><td><div class="actions">{% if g.user['role']=='admin' %}<a class="button light" href="{{ url_for('user_edit', user_id=user['id']) }}">Edit</a><form method="post" action="{{ url_for('user_delete', user_id=user['id']) }}"><button class="danger" onclick="return confirm('Delete this staff?')">Delete</button></form>{% endif %}</div></td></tr>

@app.route("/staff")
@login_required
def staff_directory():
    rows = get_db().execute(
        """SELECT full_name, phone, school_position, homeroom_class,
                  teaching_classes, subjects, weekdays
           FROM users WHERE role =? ORDER BY full_name""",
        ("staff",),
    ).fetchall()
    staff_members = []
    for row in rows:
        staff_members.append({
            "full_name": row["full_name"],
            "phone": row["phone"],
            "school_position": row["school_position"],
            "homeroom_class": row["homeroom_class"],
            "teaching_classes": json.loads(row["teaching_classes"] or "[]"),
            "subjects": json.loads(row["subjects"] or "[]"),
            "weekdays": json.loads(row["weekdays"] or "[]"),
        })
    return page("""
        <div class="topbar"><div><h1>Staff directory</h1><p class="muted">Staff contact and teaching information. Visible to signed-in school accounts.</p></div></div>
        <div class="grid">{% for member in staff_members %}<article class="card">
          <h2>{{ member['full_name'] }}</h2>
          <p><strong>Phone:</strong> {% if member['phone'] %}<a href="tel:{{ member['phone'] }}">{{ member['phone'] }}</a>{% else %}-{% endif %}</p>
          <p><strong>Position:</strong> {{ member['school_position'] or '-' }}</p>
          <p><strong>Assigned class:</strong> {{ member['homeroom_class'] or 'None' }}</p>
          <p><strong>Classes taught:</strong> {{ member['teaching_classes']|join(', ') or 'None listed' }}</p>
          <p><strong>Subjects:</strong> {{ member['subjects']|join(', ') or 'None listed' }}</p>
          <p><strong>Days:</strong> {{ member['weekdays']|join(', ') or 'None listed' }}</p>
        </article>{% else %}<div class="card">No staff profiles have been registered yet.</div>{% endfor %}</div>
        """, "Staff directory", "staff", staff_members=staff_members)



@app.route("/offices", methods=("GET", "POST"))
@login_required
def offices():
    db = get_db()
    if request.method == "POST":
        if g.user["role"] != "admin":
            flash("Only an administrator can edit office information.", "error")
            return redirect(url_for("offices"))
        office_id = request.form.get("office_id", "").strip()
        leader = request.form.get("leader", "").strip()
        members = request.form.get("members", "").strip()
        duties = request.form.get("duties", "").strip()
        if office_id.isdigit() and leader and members and duties:
            db.execute("UPDATE offices SET leader=?, members=?, duties=? WHERE id=?",
                       (leader, members, duties, int(office_id)))
            db.commit()
            flash("Office information updated successfully.")
        else:
            flash("Complete all office fields before saving.", "error")
        return redirect(url_for("offices"))

    rows = db.execute("SELECT * FROM offices ORDER BY id").fetchall()
    return page("""
      <div class="topbar"><div><h1>School Offices</h1><p class="muted">Eight offices supporting the daily work of Belmari School.</p></div></div>
      <div class="office-grid">
      {% for office in rows %}
        <article class="card office-card">
          <h2>{{ office['office_name'] }}</h2>
          <p><strong>Shugaba / Leader</strong><br>{{ office['leader'] }}</p>
          <p><strong>Membobi / Members</strong><br>{{ office['members'] }}</p>
          <div class="office-duties"><strong>Ayyuka dalla-dalla / Detailed Duties</strong>
            <ol>{% for duty in office['duties'].split('\n') %}{% if duty.strip() %}<li>{{ duty }}</li>{% endif %}{% endfor %}</ol>
          </div>
          {% if g.user['role'] == 'admin' %}
          <details><summary class="button light">Edit office details</summary>
            <form method="post" style="margin-top:14px;">
              <input type="hidden" name="office_id" value="{{ office['id'] }}">
              <div class="field"><label>Leader</label><input name="leader" value="{{ office['leader'] }}" required></div><br>
              <div class="field"><label>Members (separate names with commas)</label><textarea name="members" required>{{ office['members'] }}</textarea></div><br>
              <div class="field"><label>Duties</label><textarea name="duties" required>{{ office['duties'] }}</textarea></div><br>
              <button>Save office</button>
            </form>
          </details>
          {% endif %}
        </article>
      {% else %}<div class="card">No offices are available.</div>{% endfor %}
      </div>
      {% if g.user['role'] != 'admin' %}<p class="muted">Contact an administrator if office information needs to be changed.</p>{% endif %}
    """, "Offices", "offices", rows=rows)


@app.route("/workplace-chat", methods=("GET", "POST"))
@login_required
def workplace_chat():
    db = get_db()
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if message:
            db.execute("INSERT INTO workplace_messages (sender_id, message) VALUES (?, ?)",
                       (g.user["id"], message[:2000]))
            db.commit()
        else:
            flash("Write a message before sending.", "error")
        return redirect(url_for("workplace_chat"))

    messages = db.execute(
        """SELECT workplace_messages.*, users.full_name AS sender_name
           FROM workplace_messages JOIN users ON users.id=workplace_messages.sender_id
           ORDER BY workplace_messages.id DESC LIMIT 100"""
    ).fetchall()
    messages = list(reversed(messages))
    return page("""
      <div class="topbar"><div><h1>Workplace Chat</h1><p class="muted">Share work-related messages with signed-in school staff.</p></div></div>
      <div class="card">
        <div class="chat-window" id="chat-window">
        {% for item in messages %}
          <div class="chat-message {{ 'mine' if item['sender_id'] == g.user['id'] else '' }}">
            <div class="chat-meta"><strong>{{ item['sender_name'] }}</strong><span>{{ item['created_at'] }}</span></div>
            <div style="white-space:pre-wrap; overflow-wrap:anywhere;">{{ item['message'] }}</div>
          </div>
        {% else %}<p class="muted">No messages yet. Start the school conversation.</p>{% endfor %}
        </div>
        <form method="post" style="margin-top:18px;">
          <label for="message"><strong>Your message</strong></label>
          <textarea id="message" name="message" maxlength="2000" placeholder="Write a message to your colleagues..." required></textarea><br>
          <button type="submit">Send message</button>
        </form>
      </div>
      <script>const chatWindow=document.getElementById('chat-window'); if(chatWindow){chatWindow.scrollTop=chatWindow.scrollHeight;}</script>
    """, "Workplace Chat", "workplace_chat", messages=messages)


@app.route("/tasks", methods=("GET", "POST"))
@login_required
def tasks():
    db = get_db()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        assigned_raw = request.form.get("assigned_to", "").strip()
        due_date = request.form.get("due_date", "").strip()
        assigned_to = int(assigned_raw) if assigned_raw.isdigit() else None
        valid_assignee = assigned_to is None or db.execute(
            "SELECT id FROM users WHERE id=?", (assigned_to,)
        ).fetchone() is not None
        if not title or not valid_assignee:
            flash("Enter a task title and select a valid staff member.", "error")
        else:
            db.execute(
                """INSERT INTO tasks (title, description, assigned_to, due_date, status, created_by)
                   VALUES (?, ?, ?, ?, 'Pending', ?)""",
                (title, description, assigned_to, due_date or None, g.user["id"]),
            )
            db.commit()
            flash("Task created successfully.")
            return redirect(url_for("tasks"))

    staff = db.execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall()
    rows = db.execute(
        """SELECT tasks.*, assignee.full_name AS assignee_name, creator.full_name AS creator_name
           FROM tasks LEFT JOIN users AS assignee ON assignee.id=tasks.assigned_to
           JOIN users AS creator ON creator.id=tasks.created_by
           ORDER BY CASE tasks.status WHEN 'Pending' THEN 0 WHEN 'In Progress' THEN 1 ELSE 2 END,
                    tasks.id DESC"""
    ).fetchall()
    return page("""
      <div class="topbar"><div><h1>Tasks</h1><p class="muted">Create tasks, assign responsibilities, and track progress.</p></div></div>
      <div class="card"><h2>Create a task</h2>
        <form method="post" class="task-form">
          <div class="field"><label>Task title *</label><input name="title" maxlength="180" required></div>
          <div class="field"><label>Assign to</label><select name="assigned_to"><option value="">Unassigned</option>{% for person in staff %}<option value="{{ person['id'] }}">{{ person['full_name'] }}</option>{% endfor %}</select></div>
          <div class="field"><label>Due date</label><input type="date" name="due_date"></div>
          <div class="field full"><label>Description</label><textarea name="description" placeholder="Describe the task and expected outcome..."></textarea></div>
          <div class="field full"><button type="submit">Create task</button></div>
        </form>
      </div><br>
      <div class="card"><h2>Task board</h2>
        {% for task in rows %}
        <article class="announcement card" style="margin-bottom:14px;">
          <div class="topbar"><div><h3>{{ task['title'] }}</h3><span class="task-status {{ 'done' if task['status'] == 'Completed' else '' }}">{{ task['status'] }}</span></div>
            <form method="post" action="{{ url_for('task_status', task_id=task['id']) }}" style="min-width:160px;">
              <label class="muted">Update status</label>
              <select name="status" onchange="this.form.submit()">
                {% for state in ['Pending', 'In Progress', 'Completed'] %}<option value="{{ state }}" {{ 'selected' if task['status'] == state else '' }}>{{ state }}</option>{% endfor %}
              </select>
            </form>
          </div>
          <p>{{ task['description'] or 'No description provided.' }}</p>
          <p class="muted"><strong>Assigned to:</strong> {{ task['assignee_name'] or 'Unassigned' }} | <strong>Created by:</strong> {{ task['creator_name'] }} | <strong>Due:</strong> {{ task['due_date'] or 'Not set' }}</p>
        </article>
        {% else %}<p class="muted">There are no tasks yet.</p>{% endfor %}
      </div>
    """, "Tasks", "tasks", rows=rows, staff=staff)


@app.post("/tasks/<int:task_id>/status")
@login_required
def task_status(task_id):
    status = request.form.get("status", "")
    if status not in ("Pending", "In Progress", "Completed"):
        flash("Choose a valid task status.", "error")
    else:
        db = get_db()
        exists = db.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
        if exists:
            db.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
            db.commit()
            flash("Task status updated.")
        else:
            flash("Task not found.", "error")
    return redirect(url_for("tasks"))



@app.route("/school-calendar", methods=("GET", "POST"))
@login_required
def school_calendar():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if year < 2000 or year > 2100 or month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1)
    else:
        month_end = date(year, month + 1, 1)
    events = get_db().execute(
        """SELECT * FROM school_events
           WHERE event_date < ? AND COALESCE(end_date, event_date) >= ?
           ORDER BY event_date, id""",
        (month_end.isoformat(), month_start.isoformat()),
    ).fetchall()
    all_events = get_db().execute("SELECT * FROM school_events ORDER BY event_date, id").fetchall()

    event_days = {}
    for event in events:
        start = date.fromisoformat(event["event_date"])
        finish = date.fromisoformat(event["end_date"] or event["event_date"])
        current = max(start, month_start)
        last = min(finish, date(year, month, calendar.monthrange(year, month)[1]))
        while current <= last:
            event_days.setdefault(current.day, []).append({
                "title": event["title"],
                "event_type": event["event_type"],
                "is_range": start != finish,
            })
            current += timedelta(days=1)

    month_calendar = calendar.Calendar(firstweekday=5)  # Saturday first
    weeks = month_calendar.monthdayscalendar(year, month)
    calendar_cells = []
    for week in weeks:
        row = []
        for weekday_index, day_number in enumerate(week):
            if not day_number:
                row.append(None)
                continue
            current_date = date(year, month, day_number)
            row.append({
                "day": day_number,
                "is_today": current_date == today,
                "is_closed": weekday_index == 6,
                "is_school_day": weekday_index <= 4,
                "events": event_days.get(day_number, []),
            })
        calendar_cells.append(row)

    previous_month = month - 1
    previous_year = year
    if previous_month == 0:
        previous_month, previous_year = 12, year - 1
    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month, next_year = 1, year + 1

    return page("""
      <div class="topbar"><div><h1>School Calendar</h1><p class="muted">Jadawalin makaranta, ranakun karatu, hutu da muhimman abubuwa.</p></div>
      {% if g.user['role'] == 'admin' %}<a class="button" href="{{ url_for('school_event_new') }}">+ Add event</a>{% endif %}</div>
      <div class="card">
        <div class="calendar-toolbar">
<a class="button light" href="{{ url_for('school_calendar', year=previous_year, month=previous_month) }}"><< Previous Month</a>
          <h2 style="margin:0;">{{ month_name }} {{ year }}</h2>
    <a class="button light" href="{{ url_for('school_calendar', year=next_year, month=next_month) }}">Next Month >></a>
        </div>
        <div class="calendar-legend">
          <span><i class="legend-dot" style="background:#2563eb;"></i>Today</span>
          <span><i class="legend-dot" style="background:#dc2626;"></i>Friday - School Closed</span>
       <span><i class="legend-dot" style="background:#3b82f6;"></i>School days (Saturday-Wednesday)</span>
        </div>
        <div class="calendar-grid">
          {% for weekday in ['Asabar','Lahadi','Litinin','Talata','Laraba','Alhamis',"Juma'a"] %}<div class="calendar-weekday">{{ weekday }}</div>{% endfor %}
          {% for week in weeks %}{% for cell in week %}
            {% if cell %}<div class="calendar-day {{ 'today' if cell.is_today else ('closed' if cell.is_closed else ('school-day' if cell.is_school_day else '')) }}">
              <div class="day-number"><span>{{ cell.day }}</span>{% if cell.is_today %}<span class="today-label">TODAY</span>{% elif cell.is_closed %}<span class="closed-label">CLOSED</span>{% endif %}</div>
              {% for event in cell.events %}<span class="calendar-event {{ 'range' if event.is_range else '' }}">{{ event.title }}</span>{% endfor %}
            </div>{% else %}<div class="calendar-day empty"></div>{% endif %}
          {% endfor %}{% endfor %}
        </div>
      </div>
      <div class="card" style="margin-top:22px;"><h2>Events / Abubuwan da aka tsara</h2>
        <div style="overflow-x:auto;"><table><thead><tr><th>Event</th><th>Date</th><th>Type</th><th>Description</th>{% if g.user['role'] == 'admin' %}<th>Actions</th>{% endif %}</tr></thead><tbody>
        {% for event in all_events %}<tr><td><strong>{{ event['title'] }}</strong></td><td>{{ event['event_date'] }}{% if event['end_date'] and event['end_date'] != event['event_date'] %} to {{ event['end_date'] }}{% endif %}</td><td>{{ event['event_type'] }}</td><td>{{ event['description'] or '-' }}</td>
        {% if g.user['role'] == 'admin' %}<td><div class="actions"><a class="button light" href="{{ url_for('school_event_edit', event_id=event['id']) }}">Edit</a><form method="post" action="{{ url_for('school_event_delete', event_id=event['id']) }}" onsubmit="return confirm('Delete this event?');"><button class="danger">Delete</button></form></div></td>{% endif %}</tr>
        {% else %}<tr><td colspan="5">No events have been added.</td></tr>{% endfor %}
        </tbody></table></div>
        {% if g.user['role'] != 'admin' %}<p class="muted">Staff access is view-only. Contact an administrator to change calendar events.</p>{% endif %}
      </div>
    """, "School Calendar", "school_calendar", year=year, month=month,
       month_name=calendar.month_name[month], weeks=calendar_cells,
       previous_year=previous_year, previous_month=previous_month,
       next_year=next_year, next_month=next_month, all_events=all_events)


@app.route("/school-calendar/events/new", methods=("GET", "POST"))
@admin_required
def school_event_new():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        end_date = request.form.get("end_date", "").strip() or event_date
        event_type = request.form.get("event_type", "General").strip() or "General"
        description = request.form.get("description", "").strip()
        try:
            start_value = date.fromisoformat(event_date)
            end_value = date.fromisoformat(end_date)
            valid_dates = end_value >= start_value
        except ValueError:
            valid_dates = False
        if not title or not valid_dates:
            flash("Enter an event title and a valid date range.", "error")
        else:
            db = get_db()
            db.execute("INSERT INTO school_events (title,event_date,end_date,event_type,description) VALUES (?,?,?,?,?)",
                       (title, event_date, end_date, event_type, description))
            db.commit()
            flash("School event added successfully.")
            return redirect(url_for("school_calendar", year=start_value.year, month=start_value.month))
    return page(SCHOOL_EVENT_FORM, "Add School Event", "school_calendar", event=None, form_title="Add event")


@app.route("/school-calendar/events/<int:event_id>/edit", methods=("GET", "POST"))
@admin_required
def school_event_edit(event_id):
    db = get_db()
    event = db.execute("SELECT * FROM school_events WHERE id=?", (event_id,)).fetchone()
    if event is None:
        flash("Event not found.", "error")
        return redirect(url_for("school_calendar"))
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        event_date = request.form.get("event_date", "").strip()
        end_date = request.form.get("end_date", "").strip() or event_date
        event_type = request.form.get("event_type", "General").strip() or "General"
        description = request.form.get("description", "").strip()
        try:
            start_value = date.fromisoformat(event_date)
            end_value = date.fromisoformat(end_date)
            valid_dates = end_value >= start_value
        except ValueError:
            valid_dates = False
        if not title or not valid_dates:
            flash("Enter an event title and a valid date range.", "error")
        else:
            db.execute("UPDATE school_events SET title=?, event_date=?, end_date=?, event_type=?, description=? WHERE id=?",
                       (title, event_date, end_date, event_type, description, event_id))
            db.commit()
            flash("School event updated successfully.")
            return redirect(url_for("school_calendar", year=start_value.year, month=start_value.month))
        event = {"id": event_id, "title": title, "event_date": event_date, "end_date": end_date,
                 "event_type": event_type, "description": description}
    return page(SCHOOL_EVENT_FORM, "Edit School Event", "school_calendar", event=event, form_title="Edit event")


@app.post("/school-calendar/events/<int:event_id>/delete")
@admin_required
def school_event_delete(event_id):
    db = get_db()
    db.execute("DELETE FROM school_events WHERE id=?", (event_id,))
    db.commit()
    flash("School event deleted.")
    return redirect(url_for("school_calendar"))


SCHOOL_EVENT_FORM = """
<div class="topbar"><div><h1>{{ form_title }}</h1><p class="muted">Add or update a school event</p></div></div>
<div class="card"><form method="post" class="event-form">
<div class="field"><label>Title</label><input type="text" name="title" maxlength="120" value="{{ event_title }}" required></div>
<div class="field"><label>Start date</label><input type="date" name="start_date" value="{{ start_date }}" required></div>
<div class="field"><label>End date (optional for one-day event)</label><input type="date" name="end_date" value="{{ end_date }}"></div>
<div class="field"><label>Event type</label><select name="event_type">{% for kind in ["General", "Holiday", "Exam", "Activity"] %}<option value="{{ kind }}" {% if kind == event_type %}selected{% endif %}>{{ kind }}</option>{% endfor %}</select></div>
<div class="field"><label>Description</label><textarea name="description">{{ description }}</textarea></div>
<div class="field full"><button type="submit">Save event</button></div>
</form></div>
"""

if __name__ == "__main__":
    app.run(debug=True)
