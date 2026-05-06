import os
import sqlite3
from functools import wraps

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["DATABASE"] = os.path.join(app.instance_path, "bugboard.sqlite")


def get_db():
    if "db" not in g:
        os.makedirs(app.instance_path, exist_ok=True)
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'Open',
            priority TEXT NOT NULL DEFAULT 'Medium',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        );
        """
    )
    db.commit()


@app.cli.command("init-db")
def init_db_command():
    init_db()
    print("Initialized the BugBoard database.")


@app.before_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = None

    if user_id is not None:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("Log in to keep building your board.", "warning")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
            return render_template("register.html", name=name, email=email)

        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("That email is already registered.", "error")
            return render_template("register.html", name=name, email=email)

        flash("Account created. Log in to start tracking issues.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)

        session.clear()
        session["user_id"] = user["id"]
        flash("Welcome back.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    projects = db.execute(
        """
        SELECT
            p.*,
            COUNT(i.id) AS issue_count,
            SUM(CASE WHEN i.status = 'Open' THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN i.status = 'In Progress' THEN 1 ELSE 0 END) AS progress_count,
            SUM(CASE WHEN i.status = 'Done' THEN 1 ELSE 0 END) AS done_count
        FROM projects p
        LEFT JOIN issues i ON i.project_id = p.id
        WHERE p.user_id = ?
        GROUP BY p.id
        ORDER BY p.created_at DESC
        """,
        (g.user["id"],),
    ).fetchall()

    status = request.args.get("status", "All")
    priority = request.args.get("priority", "All")
    search = request.args.get("q", "").strip()
    issues = fetch_issues(status=status, priority=priority, search=search)
    counts = issue_counts()

    return render_template(
        "dashboard.html",
        projects=projects,
        issues=issues,
        counts=counts,
        selected_status=status,
        selected_priority=priority,
        search=search,
    )


@app.route("/projects", methods=["POST"])
@login_required
def create_project():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()

    if not name:
        flash("Project name is required.", "error")
        return redirect(url_for("dashboard"))

    db = get_db()
    db.execute(
        "INSERT INTO projects (user_id, name, description) VALUES (?, ?, ?)",
        (g.user["id"], name, description),
    )
    db.commit()
    flash("Project created.", "success")
    return redirect(url_for("dashboard"))


@app.route("/projects/<int:project_id>")
@login_required
def project_detail(project_id):
    project = get_project(project_id)
    issues = get_db().execute(
        """
        SELECT * FROM issues
        WHERE project_id = ? AND user_id = ?
        ORDER BY
            CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            created_at DESC
        """,
        (project["id"], g.user["id"]),
    ).fetchall()
    return render_template("project.html", project=project, issues=issues)


@app.route("/projects/<int:project_id>/issues/new", methods=["GET", "POST"])
@login_required
def create_issue(project_id):
    project = get_project(project_id)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "Open")
        priority = request.form.get("priority", "Medium")

        if not title:
            flash("Issue title is required.", "error")
            return render_template("issue_form.html", project=project, issue=None)

        db = get_db()
        db.execute(
            """
            INSERT INTO issues (project_id, user_id, title, description, status, priority)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project["id"], g.user["id"], title, description, status, priority),
        )
        db.commit()
        flash("Issue created.", "success")
        return redirect(url_for("project_detail", project_id=project["id"]))

    return render_template("issue_form.html", project=project, issue=None)


@app.route("/issues/<int:issue_id>/edit", methods=["GET", "POST"])
@login_required
def edit_issue(issue_id):
    issue = get_issue(issue_id)
    project = get_project(issue["project_id"])

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "Open")
        priority = request.form.get("priority", "Medium")

        if not title:
            flash("Issue title is required.", "error")
            return render_template("issue_form.html", project=project, issue=issue)

        db = get_db()
        db.execute(
            """
            UPDATE issues
            SET title = ?, description = ?, status = ?, priority = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?
            """,
            (title, description, status, priority, issue["id"], g.user["id"]),
        )
        db.commit()
        flash("Issue updated.", "success")
        return redirect(url_for("project_detail", project_id=project["id"]))

    return render_template("issue_form.html", project=project, issue=issue)


@app.route("/issues/<int:issue_id>/delete", methods=["POST"])
@login_required
def delete_issue(issue_id):
    issue = get_issue(issue_id)
    db = get_db()
    db.execute("DELETE FROM issues WHERE id = ? AND user_id = ?", (issue["id"], g.user["id"]))
    db.commit()
    flash("Issue deleted.", "success")
    return redirect(url_for("project_detail", project_id=issue["project_id"]))


def get_project(project_id):
    project = get_db().execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, g.user["id"]),
    ).fetchone()
    if project is None:
        abort(404)
    return project


def get_issue(issue_id):
    issue = get_db().execute(
        "SELECT * FROM issues WHERE id = ? AND user_id = ?",
        (issue_id, g.user["id"]),
    ).fetchone()
    if issue is None:
        abort(404)
    return issue


def fetch_issues(status="All", priority="All", search=""):
    query = [
        """
        SELECT i.*, p.name AS project_name
        FROM issues i
        JOIN projects p ON p.id = i.project_id
        WHERE i.user_id = ?
        """
    ]
    params = [g.user["id"]]

    if status != "All":
        query.append("AND i.status = ?")
        params.append(status)

    if priority != "All":
        query.append("AND i.priority = ?")
        params.append(priority)

    if search:
        query.append("AND (i.title LIKE ? OR i.description LIKE ? OR p.name LIKE ?)")
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])

    query.append(
        """
        ORDER BY
            CASE i.status WHEN 'Open' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END,
            CASE i.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            i.created_at DESC
        """
    )

    return get_db().execute(" ".join(query), params).fetchall()


def issue_counts():
    row = get_db().execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status = 'Open' THEN 1 ELSE 0 END) AS open,
            SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS progress,
            SUM(CASE WHEN status = 'Done' THEN 1 ELSE 0 END) AS done
        FROM issues
        WHERE user_id = ?
        """,
        (g.user["id"],),
    ).fetchone()
    return {
        "total": row["total"] or 0,
        "open": row["open"] or 0,
        "progress": row["progress"] or 0,
        "done": row["done"] or 0,
    }


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
