"""Fundação segura da Central de Afiliados; ainda em desenvolvimento."""
import hmac
import os
import secrets
import sqlite3
from pathlib import Path
from functools import wraps

from flask import (
    Flask, abort, flash, g, redirect, render_template, request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("CENTRAL_SECRET_KEY"),
        DATABASE=os.environ.get(
            "CENTRAL_DATABASE",
            str(Path(app.instance_path) / "central.sqlite3"),
        ),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,  # True ao publicar somente por HTTPS.
        PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY"):
        if app.config.get("TESTING"):
            app.config["SECRET_KEY"] = "test-only-secret-not-for-production"
        else:
            raise RuntimeError(
                "Defina CENTRAL_SECRET_KEY no ambiente antes de iniciar a aplicação."
            )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    def connect_db():
        db = sqlite3.connect(app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def init_db():
        db = connect_db()
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    price REAL,
                    affiliate_link TEXT NOT NULL DEFAULT '',
                    commission REAL,
                    notes TEXT NOT NULL DEFAULT '',
                    image_filename TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS product_images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT 'Instagram',
                    status TEXT NOT NULL DEFAULT 'Ideia',
                    planned_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                    clicks INTEGER NOT NULL DEFAULT 0,
                    orders INTEGER NOT NULL DEFAULT 0,
                    sales_value REAL NOT NULL DEFAULT 0,
                    commission_value REAL NOT NULL DEFAULT 0,
                    commission_status TEXT NOT NULL DEFAULT 'Estimada',
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
            """)
            db.commit()
        finally:
            db.close()

    init_db()

    def user_count():
        db = connect_db()
        try:
            return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        finally:
            db.close()

    @app.before_request
    def load_user_and_csrf():
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            db = connect_db()
            try:
                g.user = db.execute(
                    "SELECT id, username FROM users WHERE id = ?", (user_id,)
                ).fetchone()
            finally:
                db.close()
            if g.user is None:
                session.clear()
        if "_csrf_token" not in session:
            session["_csrf_token"] = secrets.token_urlsafe(32)

    @app.context_processor
    def inject_template_globals():
        return {"csrf_token": lambda: session.get("_csrf_token", "")}

    @app.before_request
    def protect_post_requests():
        if request.method == "POST":
            supplied = request.form.get("_csrf_token", "")
            expected = session.get("_csrf_token", "")
            if not expected or not supplied or not hmac.compare_digest(supplied, expected):
                abort(400, description="Token de segurança inválido. Atualize a página e tente novamente.")

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)
        return wrapped

    @app.get("/")
    @login_required
    def dashboard():
        db = connect_db()
        try:
            product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            post_count = db.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        finally:
            db.close()
        return render_template(
            "dashboard.html", product_count=product_count, post_count=post_count
        )

    @app.route("/configurar", methods=["GET", "POST"])
    def setup():
        if user_count() > 0:
            return redirect(url_for("login"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            confirmation = request.form.get("confirmation", "")
            if len(username) < 3 or len(username) > 40:
                flash("O usuário precisa ter de 3 a 40 caracteres.", "error")
            elif len(password) < 12:
                flash("Use uma senha com pelo menos 12 caracteres.", "error")
            elif password != confirmation:
                flash("As senhas não coincidem.", "error")
            else:
                db = connect_db()
                try:
                    # Recheck inside the write transaction to avoid a second first-user.
                    db.execute("BEGIN IMMEDIATE")
                    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] != 0:
                        db.rollback()
                        return redirect(url_for("login"))
                    cursor = db.execute(
                        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                        (username, generate_password_hash(password)),
                    )
                    db.commit()
                    session.clear()
                    session["user_id"] = cursor.lastrowid
                    session.permanent = True
                    session["_csrf_token"] = secrets.token_urlsafe(32)
                    return redirect(url_for("dashboard"))
                except sqlite3.IntegrityError:
                    db.rollback()
                    flash("Esse usuário já existe. Escolha outro.", "error")
                finally:
                    db.close()
        return render_template("setup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if user_count() == 0:
            return redirect(url_for("setup"))
        if g.user is not None:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            db = connect_db()
            try:
                user = db.execute(
                    "SELECT id, username, password_hash FROM users WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone()
            finally:
                db.close()
            if user and check_password_hash(user["password_hash"], password):
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = True
                session["_csrf_token"] = secrets.token_urlsafe(32)
                destination = request.args.get("next", "")
                if not destination.startswith("/") or destination.startswith("//"):
                    destination = url_for("dashboard")
                return redirect(destination)
            flash("Usuário ou senha incorretos.", "error")
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "central-afiliados-next"}

    return app


if __name__ == "__main__":
    application = create_app()
    # Apenas desenvolvimento local. Não publicar o servidor Flask diretamente na internet.
    application.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
