"""
VulnShop - a DELIBERATELY VULNERABLE web application.

WEB404 Secure Coding Practices - Practical Assignment 4
"Configure and test a Web Application Firewall (WAF) to protect against
 common server-side attacks."

This application exists only as a target that the WAF (ModSecurity v3 +
OWASP Core Rule Set) is placed in front of. Every endpoint below contains a
classic server-side flaw from Unit II/III of the module descriptor:

    /login            SQL injection (auth bypass) + no brute-force protection
    /products?q=      SQL injection (UNION / error based)
    /product?id=      SQL injection (boolean / time based blind)
    /tools/ping       OS command injection
    /docs?file=       Directory traversal / local file inclusion
    /upload           Unrestricted file upload (+ filename path traversal)
    /fetch?url=       Server-side request forgery (SSRF)
    /report?year=     Information disclosure (stack trace)
    /public/...       Information disclosure (.env, backups, .git)
    /greet?name=      Reflected XSS (client-side, included for completeness)

DO NOT deploy this anywhere reachable from a network you do not control.
docker-compose.yml binds it to 127.0.0.1 only.
"""

import os
import sqlite3
import subprocess
import traceback
import urllib.request

from flask import Flask, Response, render_template, request, send_from_directory
from markupsafe import Markup, escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", "/tmp/vulnshop.db")
DOCS_DIR = os.path.join(BASE_DIR, "public", "docs")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# --------------------------------------------------------------------------- #
# Database bootstrap
# --------------------------------------------------------------------------- #
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(
        """
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS products;
        DROP TABLE IF EXISTS feedback;
        CREATE TABLE users (
            id INTEGER PRIMARY KEY, username TEXT, password TEXT,
            role TEXT, email TEXT
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY, name TEXT, category TEXT, price REAL
        );
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY, name TEXT, message TEXT
        );
        """
    )
    # Plain-text passwords are intentional (sensitive data exposure demo).
    cur.executemany(
        "INSERT INTO users (username, password, role, email) VALUES (?,?,?,?)",
        [
            ("admin", "S3cr3t-Adm1n!", "administrator", "admin@vulnshop.local"),
            ("alice", "alice2026", "customer", "alice@vulnshop.local"),
            ("bob", "hunter2", "customer", "bob@vulnshop.local"),
        ],
    )
    cur.executemany(
        "INSERT INTO products (name, category, price) VALUES (?,?,?)",
        [
            ("Laptop Pro 14", "electronics", 1299.00),
            ("Wireless Mouse", "electronics", 25.50),
            ("Mechanical Keyboard", "electronics", 89.99),
            ("O'Reilly Web Security Book", "books", 45.00),
            ("Rock & Roll Vinyl", "music", 30.00),
            ("Bhutanese Red Rice 5kg", "grocery", 12.75),
        ],
    )
    con.commit()
    con.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def db():
    return sqlite3.connect(DB_PATH)


def page(title, body, status=200):
    # title fragments are already HTML-escaped by the callers
    return render_template("page.html", title=Markup(title), body=Markup(body)), status


# --------------------------------------------------------------------------- #
# Basic pages
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# 1. SQL injection - authentication bypass (and brute force: no rate limit)
# --------------------------------------------------------------------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    username = request.form.get("username", "")
    password = request.form.get("password", "")
    # VULNERABLE: user input concatenated straight into SQL.
    query = (
        "SELECT id, username, role FROM users "
        f"WHERE username = '{username}' AND password = '{password}'"
    )
    try:
        row = db().execute(query).fetchone()
    except sqlite3.Error as exc:
        # VULNERABLE: database error + query echoed back (information disclosure)
        return page("Database error",
                    f"<pre class='err'>sqlite3.OperationalError: {escape(exc)}\n"
                    f"Query: {escape(query)}</pre>", 500)
    if row:
        return page("Welcome",
                    f"<p class='ok'>Welcome, <b>{escape(row[1])}</b>! "
                    f"Role: {escape(row[2])}</p>")
    return page("Login failed", "<p class='bad'>Invalid username or password.</p>", 401)


# --------------------------------------------------------------------------- #
# 2. SQL injection - UNION / error based (search)
# --------------------------------------------------------------------------- #
@app.route("/products")
def products():
    q = request.args.get("q", "")
    # VULNERABLE: string concatenation into a LIKE clause.
    query = f"SELECT id, name, price FROM products WHERE name LIKE '%{q}%'"
    try:
        rows = db().execute(query).fetchall()
    except sqlite3.Error as exc:
        return page("Database error",
                    f"<pre class='err'>sqlite3.OperationalError: {escape(exc)}\n"
                    f"Query: {escape(query)}</pre>", 500)
    items = "".join(
        f"<tr><td>{escape(r[0])}</td><td>{escape(r[1])}</td><td>{escape(r[2])}</td></tr>"
        for r in rows
    )
    return page(f"Search results for: {escape(q)}",
                f"<table><tr><th>ID</th><th>Name</th><th>Price</th></tr>{items}</table>"
                f"<p>{len(rows)} result(s)</p>")


# --------------------------------------------------------------------------- #
# 3. SQL injection - boolean / time based blind (product detail)
# --------------------------------------------------------------------------- #
@app.route("/product")
def product():
    pid = request.args.get("id", "1")
    query = f"SELECT name, price FROM products WHERE id = {pid}"  # VULNERABLE
    try:
        row = db().execute(query).fetchone()
    except sqlite3.Error:
        # Generic error: the attacker must infer results "blind".
        return page("Product", "<p class='bad'>Product not found.</p>", 404)
    if not row:
        return page("Product", "<p class='bad'>Product not found.</p>", 404)
    return page("Product", f"<p class='ok'>In stock: <b>{escape(row[0])}</b> - "
                           f"Nu. {escape(row[1])}</p>")


# --------------------------------------------------------------------------- #
# 4. OS command injection
# --------------------------------------------------------------------------- #
@app.route("/tools/ping")
def ping():
    host = request.args.get("host", "")
    if not host:
        return render_template("ping.html")
    # VULNERABLE: shell=True with user input.
    proc = subprocess.run(f"ping -c 1 -W 1 {host}", shell=True,
                          capture_output=True, text=True, timeout=10)
    return page(f"Ping {escape(host)}",
                f"<pre>{escape(proc.stdout + proc.stderr)}</pre>")


# --------------------------------------------------------------------------- #
# 5. Directory traversal / LFI
# --------------------------------------------------------------------------- #
@app.route("/docs")
def docs():
    name = request.args.get("file", "")
    if not name:
        listing = "".join(f"<li><a href='/docs?file={escape(f)}'>{escape(f)}</a></li>"
                          for f in sorted(os.listdir(DOCS_DIR)))
        return page("Documentation", f"<ul>{listing}</ul>")
    # VULNERABLE: no canonicalisation; '../' and absolute paths escape DOCS_DIR.
    path = os.path.join(DOCS_DIR, name)
    try:
        with open(path, "r", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        return page("Error", f"<pre class='err'>{escape(exc)}</pre>", 404)
    return page(f"Document: {escape(name)}", f"<pre>{escape(content)}</pre>")


# --------------------------------------------------------------------------- #
# 6. Unrestricted file upload
# --------------------------------------------------------------------------- #
@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "GET":
        return render_template("upload.html")
    f = request.files.get("file")
    if not f or not f.filename:
        return page("Upload", "<p class='bad'>No file supplied.</p>", 400)
    # VULNERABLE: original filename trusted (extension, content and path).
    dest = os.path.join(UPLOAD_DIR, f.filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    f.save(dest)
    return page("Upload complete",
                f"<p class='ok'>Stored as <a href='/uploads/{escape(f.filename)}'>"
                f"{escape(os.path.normpath(dest))}</a></p>")


@app.route("/uploads/<path:name>")
def uploaded(name):
    # Served inline with a guessed MIME type -> uploaded .html/.svg = stored XSS.
    return send_from_directory(UPLOAD_DIR, name)


# --------------------------------------------------------------------------- #
# 7. Server-side request forgery
# --------------------------------------------------------------------------- #
@app.route("/fetch")
def fetch():
    url = request.args.get("url", "")
    if not url:
        return render_template("fetch.html")
    try:
        # VULNERABLE: any scheme (file://), any host (127.0.0.1, 169.254.169.254).
        with urllib.request.urlopen(url, timeout=3) as resp:
            body = resp.read(4000).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return page("Fetch failed", f"<pre class='err'>{escape(exc)}</pre>", 502)
    return page(f"Preview of {escape(url)}", f"<pre>{escape(body)}</pre>")


@app.route("/internal/admin")
def internal_admin():
    # "Protected" by source IP only - reachable through the SSRF above.
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return page("Not found", "<p>Not found.</p>", 404)
    return page("Internal admin",
                "<p>INTERNAL ADMIN PANEL - db_password=Pr0d-DB-Pa55 "
                "aws_key=AKIAEXAMPLEKEY123</p>")


# --------------------------------------------------------------------------- #
# 8. Information disclosure
# --------------------------------------------------------------------------- #
@app.route("/report")
def report():
    year = request.args.get("year", "2026")
    try:
        total = 1000 / (int(year) - 2026) if year != "2026" else 0
        return page("Sales report", f"<p>Sales index for {escape(year)}: {total:.2f}</p>")
    except Exception:  # noqa: BLE001
        # VULNERABLE: full stack trace returned to the client.
        return Response(traceback.format_exc(), status=500, mimetype="text/plain")


@app.route("/public/<path:name>")
def public_files(name):
    # VULNERABLE: serves dot-files and backups that were never meant to be public.
    return send_from_directory(PUBLIC_DIR, name)


@app.route("/.env")
@app.route("/.git/config")
@app.route("/backup/db_backup.sql")
def leaked_files():
    mapping = {"/.env": ".env", "/.git/config": "git_config",
               "/backup/db_backup.sql": "backup/db_backup.sql"}
    return send_from_directory(PUBLIC_DIR, mapping[request.path],
                               mimetype="text/plain")


# --------------------------------------------------------------------------- #
# 9. Feedback form (used for false-positive testing) and reflected XSS
# --------------------------------------------------------------------------- #
@app.route("/feedback", methods=["GET", "POST"])
def feedback():
    if request.method == "GET":
        return render_template("feedback.html")
    name = request.form.get("name", "")
    message = request.form.get("message", "")
    con = db()
    con.execute("INSERT INTO feedback (name, message) VALUES (?, ?)", (name, message))
    con.commit()
    return page("Thank you", f"<p class='ok'>Thanks {escape(name)}, "
                             "your feedback was recorded.</p>")


@app.route("/greet")
def greet():
    name = request.args.get("name", "guest")
    return page("Greeting", f"<p>Hello, {name}!</p>")  # VULNERABLE: no encoding


@app.after_request
def leak_headers(resp):
    # VULNERABLE: technology fingerprinting headers.
    resp.headers["X-Powered-By"] = "Flask/3 Python/3.12"
    return resp


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
