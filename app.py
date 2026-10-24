"""Fundação segura da Central de Afiliados; ainda em desenvolvimento."""
import hmac
import os
import secrets
import sqlite3
from pathlib import Path
from functools import wraps

from flask import (
    Flask, abort, flash, g, redirect, render_template, request, session, url_for, send_from_directory
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
            # Migração segura para usuários e publicações, sem apagar dados existentes.
            user_columns = {row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()}
            if "is_admin" not in user_columns:
                db.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
            if db.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] == 0:
                first_user = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
                if first_user:
                    db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (first_user["id"],))
            # Migração segura para publicações, sem apagar dados existentes.
            post_columns = {row[1] for row in db.execute("PRAGMA table_info(posts)").fetchall()}
            if "content_type" not in post_columns:
                db.execute("ALTER TABLE posts ADD COLUMN content_type TEXT NOT NULL DEFAULT 'story'")
            if "image_filename" not in post_columns:
                db.execute("ALTER TABLE posts ADD COLUMN image_filename TEXT NOT NULL DEFAULT ''")
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
            admin_row = db.execute("SELECT is_admin FROM users WHERE id = ?", (g.user["id"],)).fetchone()
            is_admin = bool(admin_row and admin_row["is_admin"])
        finally:
            db.close()
        return render_template(
            "dashboard.html", product_count=product_count, post_count=post_count, is_admin=is_admin
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

    @app.route("/usuarios", methods=["GET", "POST"])
    @login_required
    def users_admin():
        db = connect_db()
        try:
            current = db.execute("SELECT is_admin FROM users WHERE id = ?", (g.user["id"],)).fetchone()
            if not current or not current["is_admin"]:
                abort(403)
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
                    try:
                        db.execute(
                            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 0)",
                            (username, generate_password_hash(password)),
                        )
                        db.commit()
                        flash("Usuário criado com sucesso.", "success")
                        return redirect(url_for("users_admin"))
                    except sqlite3.IntegrityError:
                        db.rollback()
                        flash("Esse usuário já existe. Escolha outro.", "error")
            users = db.execute("SELECT id, username, is_admin, created_at FROM users ORDER BY id").fetchall()
            return render_template("users.html", users=users)
        finally:
            db.close()

    @app.post("/logout")
    @login_required
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "central-afiliados-next"}

    from werkzeug.utils import secure_filename
    import uuid
    upload_dir = Path(app.static_folder) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/uploads/<path:filename>")
    @login_required
    def uploaded_file(filename):
        return send_from_directory(upload_dir, filename)
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

    @app.get("/produtos")
    @login_required
    def products():
        q = request.args.get("q", "").strip()
        db = connect_db()
        try:
            sql = """SELECT p.*, (SELECT COUNT(*) FROM product_images i WHERE i.product_id=p.id) AS extra_images FROM products p"""
            if q:
                rows = db.execute(sql + " WHERE p.name LIKE ? OR p.category LIKE ? ORDER BY p.id DESC", (f"%{q}%", f"%{q}%")).fetchall()
            else:
                rows = db.execute(sql + " ORDER BY p.id DESC").fetchall()
            products_data = [dict(row) for row in rows]
        finally:
            db.close()
        return render_template("products.html", products=products_data, q=q)

    @app.route("/produtos/novo", methods=["GET", "POST"])
    @app.route("/produtos/<int:product_id>/editar", methods=["GET", "POST"])
    @login_required
    def product_form(product_id=None):
        db = connect_db()
        try:
            product = db.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone() if product_id else None
            if product_id and product is None:
                abort(404)
            if request.method == "POST":
                name = request.form.get("name", "").strip()
                category = request.form.get("category", "").strip()
                link = request.form.get("affiliate_link", "").strip()
                notes = request.form.get("notes", "").strip()
                try:
                    price_raw = request.form.get("price", "").strip().replace(",", ".")
                    commission_raw = request.form.get("commission", "").strip().replace("%", "").replace(",", ".")
                    price = float(price_raw) if price_raw else None
                    commission = float(commission_raw) if commission_raw else None
                    if (price is not None and price <= 0) or (commission is not None and not 0 < commission <= 100):
                        raise ValueError()
                except ValueError:
                    flash("Informe um preço positivo e uma comissão entre 0 e 100%.", "error")
                    return redirect(request.url)
                if not name:
                    flash("Informe o nome do produto.", "error")
                    return redirect(request.url)
                if product:
                    db.execute("UPDATE products SET name=?, category=?, price=?, affiliate_link=?, commission=?, notes=? WHERE id=?", (name, category, price, link, commission, notes, product_id))
                    pid = product_id
                else:
                    cur = db.execute("INSERT INTO products (name, category, price, affiliate_link, commission, notes) VALUES (?, ?, ?, ?, ?, ?)", (name, category, price, link, commission, notes))
                    pid = cur.lastrowid
                main = db.execute("SELECT image_filename FROM products WHERE id=?", (pid,)).fetchone()["image_filename"]
                extra_count = db.execute("SELECT COUNT(*) FROM product_images WHERE product_id=?", (pid,)).fetchone()[0]
                for photo in request.files.getlist("photos"):
                    if not photo or not photo.filename: continue
                    ext = Path(secure_filename(photo.filename)).suffix.lower()
                    if ext not in allowed_extensions:
                        flash("Formato não aceito. Use PNG, JPG, WEBP ou GIF.", "error")
                        continue
                    if (1 if main else 0) + extra_count >= 10:
                        flash("Limite de 10 fotos por produto atingido.", "error")
                        break
                    filename = uuid.uuid4().hex + ext
                    photo.save(upload_dir / filename)
                    if not main:
                        db.execute("UPDATE products SET image_filename=? WHERE id=?", (filename, pid))
                        main = filename
                    else:
                        db.execute("INSERT INTO product_images (product_id, filename) VALUES (?, ?)", (pid, filename))
                        extra_count += 1
                db.commit()
                flash("Produto salvo.", "success")
                return redirect(url_for("products"))
            extras = db.execute("SELECT id, filename FROM product_images WHERE product_id=? ORDER BY id", (product_id,)).fetchall() if product_id else []
            return render_template("product_form.html", product=product, product_photos=extras)
        finally:
            db.close()

    @app.route("/conteudo", methods=["GET", "POST"])
    @login_required
    def content():
        db = connect_db()
        try:
            if request.method == "POST":
                product_id = request.form.get("product_id", type=int)
                content_type = request.form.get("content_type", "story").strip().lower()
                caption = request.form.get("caption", "").strip()
                if content_type not in {"story", "post"}:
                    abort(400)
                product = db.execute("SELECT id FROM products WHERE id=?", (product_id,)).fetchone() if product_id else None
                if product is None:
                    flash("Escolha um produto cadastrado.", "error")
                    return redirect(url_for("content", tipo=content_type, view="new"))
                photo = request.files.get("ready_image")
                filename = ""
                if photo and photo.filename:
                    ext = Path(secure_filename(photo.filename)).suffix.lower()
                    if ext not in allowed_extensions:
                        flash("Imagem inválida. Use PNG, JPG, WEBP ou GIF.", "error")
                        return redirect(url_for("content", tipo=content_type, view="new"))
                    filename = uuid.uuid4().hex + ext
                    photo.save(upload_dir / filename)
                db.execute(
                    "INSERT INTO posts (product_id, caption, platform, status, content_type, image_filename) VALUES (?, ?, 'Instagram', 'Aguardando', ?, ?)",
                    (product_id, caption, content_type, filename),
                )
                db.commit()
                flash("Publicação criada e salva.", "success")
                return redirect(url_for("content", tipo=content_type, status="Aguardando"))
            products_data = [dict(row) for row in db.execute("SELECT id, name, category, price, affiliate_link, notes, image_filename FROM products ORDER BY name COLLATE NOCASE").fetchall()]
            posts_data = [dict(row) for row in db.execute("""SELECT posts.*, products.name AS product_name, products.affiliate_link AS affiliate_link FROM posts LEFT JOIN products ON products.id=posts.product_id ORDER BY posts.id DESC""").fetchall()]
        finally:
            db.close()
        return render_template("content.html", products=products_data, posts=posts_data, tipo=request.args.get("tipo", "story"))

    @app.post("/conteudo/<int:post_id>/status")
    @login_required
    def content_status(post_id):
        status = request.form.get("status", "")
        allowed_statuses = {"Aguardando", "Fazendo", "Pronto para postar", "Publicado"}
        if status not in allowed_statuses:
            abort(400)
        db = connect_db()
        try:
            cur = db.execute("UPDATE posts SET status=? WHERE id=?", (status, post_id))
            if cur.rowcount == 0:
                abort(404)
            db.commit()
        finally:
            db.close()
        flash("Status atualizado.", "success")
        return redirect(url_for("content", tipo=request.form.get("content_type", "story"), status=status))

    @app.post("/conteudo/<int:post_id>/excluir")
    @login_required
    def content_delete(post_id):
        db = connect_db()
        try:
            row = db.execute("SELECT image_filename, content_type, status FROM posts WHERE id=?", (post_id,)).fetchone()
            if row is None:
                abort(404)
            filename = row["image_filename"]
            content_type = request.form.get("content_type", row["content_type"] or "story")
            status = request.form.get("status", row["status"] or "Aguardando")
            db.execute("DELETE FROM posts WHERE id=?", (post_id,))
            db.commit()
            if filename:
                (upload_dir / filename).unlink(missing_ok=True)
            flash("Publicação excluída.", "success")
        finally:
            db.close()
        return redirect(url_for("content", tipo=content_type, status=status))

    @app.post("/produtos/<int:product_id>/excluir")
    @login_required
    def product_delete(product_id):
        db = connect_db()
        try:
            row = db.execute("SELECT image_filename FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None: abort(404)
            names = [row["image_filename"]] if row["image_filename"] else []
            names += [x["filename"] for x in db.execute("SELECT filename FROM product_images WHERE product_id=?", (product_id,)).fetchall()]
            db.execute("DELETE FROM products WHERE id=?", (product_id,))
            db.commit()
            for filename in names: (upload_dir / filename).unlink(missing_ok=True)
            flash("Produto excluído.", "success")
        finally:
            db.close()
        return redirect(url_for("products"))

    return app


if __name__ == "__main__":
    application = create_app()
    # Apenas desenvolvimento local. Não publicar o servidor Flask diretamente na internet.
    application.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=False,
    )
