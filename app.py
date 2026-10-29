"""Fundação segura da Central de Afiliados; ainda em desenvolvimento."""
import hmac
import base64
import json
import mimetypes
import urllib.error
import urllib.request
import os
import secrets
import sqlite3
from pathlib import Path
from functools import wraps

from flask import (
    Flask, abort, flash, g, redirect, render_template, request, session, url_for, send_from_directory
)
from werkzeug.security import check_password_hash, generate_password_hash

# Carrega configurações locais de .env quando existir; variáveis já exportadas têm prioridade.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
except ImportError:
    pass


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
                CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
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
                CREATE TABLE IF NOT EXISTS calendar_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    task_type TEXT NOT NULL DEFAULT 'Tarefa',
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pendente',
                    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
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
            # Categorias iniciais e categorias já usadas nos produtos, sem apagar dados.
            initial_categories = ["Academia", "Corrida", "Pesca", "Moda feminina", "Moda masculina", "Moda infantil", "Suplementos", "Eletrônicos", "Celulares e acessórios", "Casa e decoração", "Cozinha", "Beleza", "Cuidados pessoais", "Pets", "Automotivo", "Games", "Esportes", "Camping e aventura", "Ferramentas", "Brinquedos", "Papelaria", "Bebês", "Calçados", "Bolsas e acessórios", "Relógios e joias", "Jardim", "Mercado", "Livros", "Móveis", "Viagem", "Diversos"]
            for category_name in initial_categories:
                db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category_name,))
            for category_row in db.execute("SELECT DISTINCT TRIM(category) AS name FROM products WHERE TRIM(category) <> ''").fetchall():
                db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category_row["name"],))
            task_columns = {row[1] for row in db.execute("PRAGMA table_info(calendar_tasks)").fetchall()}
            if "color" not in task_columns:
                db.execute("ALTER TABLE calendar_tasks ADD COLUMN color TEXT NOT NULL DEFAULT 'blue'")

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

    @app.route("/calendario", methods=["GET", "POST"])
    @login_required
    def calendar():
        import datetime
        db = connect_db()
        try:
            if request.method == "POST":
                title = request.form.get("title", "").strip()
                description = request.form.get("description", "").strip()
                task_type = request.form.get("task_type", "Tarefa").strip()
                due_at = request.form.get("due_at", "").strip()
                product_id = request.form.get("product_id", "").strip()
                color = request.form.get("color", "blue").strip()
                if color not in {"yellow", "blue", "green", "red", "pink"}:
                    color = "blue"
                try:
                    datetime.datetime.strptime(due_at, "%Y-%m-%dT%H:%M")
                    linked_product = int(product_id) if product_id else None
                    if linked_product is not None and not db.execute("SELECT id FROM products WHERE id = ?", (linked_product,)).fetchone():
                        linked_product = None
                    if not title:
                        raise ValueError("title")
                    db.execute("INSERT INTO calendar_tasks (title, description, task_type, due_at, product_id, color) VALUES (?, ?, ?, ?, ?, ?)", (title, description, task_type, due_at, linked_product, color))
                    db.commit()
                    flash("Compromisso adicionado à agenda.", "success")
                    return redirect(url_for("calendar", dia=due_at[:10]))
                except (ValueError, sqlite3.Error):
                    db.rollback()
                    flash("Não foi possível salvar. Confira o título, a data e o horário.", "error")
            today = datetime.date.today()
            try:
                selected_day = datetime.datetime.strptime(request.args.get("dia", ""), "%Y-%m-%d").date()
            except ValueError:
                selected_day = today
            week_start = selected_day - datetime.timedelta(days=selected_day.weekday())
            week_days = [week_start + datetime.timedelta(days=i) for i in range(7)]
            week_end = week_start + datetime.timedelta(days=7)
            tasks = db.execute("SELECT t.*, p.name AS product_name FROM calendar_tasks t LEFT JOIN products p ON p.id=t.product_id WHERE t.due_at >= ? AND t.due_at < ? ORDER BY t.due_at", (week_start.isoformat() + "T00:00", week_end.isoformat() + "T00:00")).fetchall()
            day_tasks = [task for task in tasks if task["due_at"][:10] == selected_day.isoformat()]
            day_counts = {day.isoformat(): sum(1 for task in tasks if task["due_at"][:10] == day.isoformat()) for day in week_days}
            products = db.execute("SELECT id, name FROM products ORDER BY name").fetchall()
            task_stats = {
                "pending": db.execute("SELECT COUNT(*) FROM calendar_tasks WHERE status='Pendente'").fetchone()[0],
                "done": db.execute("SELECT COUNT(*) FROM calendar_tasks WHERE status='Concluída'").fetchone()[0],
                "overdue": db.execute("SELECT COUNT(*) FROM calendar_tasks WHERE status!='Concluída' AND due_at < ?", (today.isoformat() + "T00:00",)).fetchone()[0],
            }
        finally:
            db.close()
        return render_template("calendar.html", tasks=tasks, day_tasks=day_tasks, products=products, selected_day=selected_day, week_days=week_days, day_counts=day_counts, prev_day=selected_day - datetime.timedelta(days=1), next_day=selected_day + datetime.timedelta(days=1), task_stats=task_stats)

    @app.post("/calendario/<int:task_id>/status")
    @login_required
    def calendar_task_status(task_id):
        status = request.form.get("status", "")
        if status not in ("Pendente", "Em andamento", "Concluída"):
            abort(400)
        db = connect_db()
        try:
            db.execute("UPDATE calendar_tasks SET status=? WHERE id=?", (status, task_id))
            db.commit()
        finally:
            db.close()
        return redirect(url_for("calendar", dia=request.form.get("dia", "")))

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
            require_admin(db)
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

    def require_admin(db):
        current = db.execute("SELECT is_admin FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if not current or not current["is_admin"]:
            abort(403)

    @app.get("/usuarios/<int:user_id>")
    @login_required
    def user_detail(user_id):
        db = connect_db()
        try:
            require_admin(db)
            user = db.execute("SELECT id, username, is_admin, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None: abort(404)
            return render_template("user_detail.html", user=user, is_self=(user["id"] == g.user["id"]))
        finally: db.close()

    @app.route("/usuarios/<int:user_id>/editar", methods=["GET", "POST"])
    @login_required
    def user_edit(user_id):
        db = connect_db()
        try:
            require_admin(db)
            user = db.execute("SELECT id, username, is_admin, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None: abort(404)
            if request.method == "POST":
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                confirmation = request.form.get("confirmation", "")
                if len(username) < 3 or len(username) > 40: flash("O usuário precisa ter de 3 a 40 caracteres.", "error")
                elif password and len(password) < 12: flash("A nova senha precisa ter pelo menos 12 caracteres.", "error")
                elif password != confirmation: flash("As senhas não coincidem.", "error")
                else:
                    try:
                        if password:
                            db.execute("UPDATE users SET username = ?, password_hash = ? WHERE id = ?", (username, generate_password_hash(password), user_id))
                        else:
                            db.execute("UPDATE users SET username = ? WHERE id = ?", (username, user_id))
                        db.commit()
                        if user_id == g.user["id"]:
                            session.clear()
                            session["user_id"] = user_id
                            session.permanent = True
                            session["_csrf_token"] = secrets.token_urlsafe(32)
                        flash("Usuário atualizado com sucesso.", "success")
                        return redirect(url_for("users_admin"))
                    except sqlite3.IntegrityError:
                        db.rollback()
                        flash("Esse nome de usuário já existe. Escolha outro.", "error")
            return render_template("user_edit.html", user=user)
        finally: db.close()

    @app.post("/usuarios/<int:user_id>/excluir")
    @login_required
    def user_delete(user_id):
        db = connect_db()
        try:
            require_admin(db)
            user = db.execute("SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
            if user is None: abort(404)
            if user_id == g.user["id"]:
                flash("Você não pode excluir sua própria conta por aqui.", "error")
                return redirect(url_for("users_admin"))
            if user["is_admin"] and db.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0] <= 1:
                flash("Não é possível excluir o último administrador.", "error")
                return redirect(url_for("users_admin"))
            db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.commit()
            flash("Usuário excluído.", "success")
            return redirect(url_for("users_admin"))
        finally: db.close()

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

    @app.route("/produtos/buscar-shopee", methods=["GET", "POST"])
    @login_required
    def shopee_product_search():
        from shopee_affiliate import ShopeeAPIError, ShopeeAffiliateClient, search_product_offers

        keyword = request.form.get("keyword", "").strip() if request.method == "POST" else request.args.get("q", "").strip()
        offers = []
        page_info = {}
        searched = False
        if request.method == "POST" and keyword:
            searched = True
            try:
                result = search_product_offers(
                    ShopeeAffiliateClient(),
                    keyword=keyword,
                    page=1,
                    limit=10,
                    sort_type=5,
                )
                offers = result.get("nodes") or []
                page_info = result.get("pageInfo") or {}
                if not offers:
                    flash("A Shopee não retornou produtos para essa busca. Tente outra palavra-chave.", "info")
            except ShopeeAPIError as exc:
                flash(str(exc), "error")
        elif request.method == "POST":
            flash("Digite o nome de um produto para pesquisar.", "error")

        return render_template(
            "shopee_search.html",
            keyword=keyword,
            offers=offers,
            page_info=page_info,
            searched=searched,
        )

    @app.get("/produtos")
    @login_required
    def products():
        q = request.args.get("q", "").strip()
        db = connect_db()
        try:
            sql = """SELECT p.*, (SELECT COUNT(*) FROM product_images i WHERE i.product_id=p.id) AS extra_images, EXISTS(SELECT 1 FROM posts po WHERE po.product_id=p.id AND po.status='Publicado') AS has_published FROM products p"""
            if q:
                rows = db.execute(sql + " WHERE p.name LIKE ? OR p.category LIKE ? ORDER BY p.id DESC", (f"%{q}%", f"%{q}%")).fetchall()
            else:
                rows = db.execute(sql + " ORDER BY p.id DESC").fetchall()
            products_data = [dict(row) for row in rows]
            for product in products_data:
                photo_rows = db.execute(
                    "SELECT filename FROM product_images WHERE product_id=? ORDER BY id",
                    (product["id"],)
                ).fetchall()
                product["gallery_filenames"] = ([product["image_filename"]] if product["image_filename"] else []) + [photo["filename"] for photo in photo_rows]
        finally:
            db.close()
        return render_template("products.html", products=products_data, q=q)


    @app.route("/produtos/importar-link", methods=["POST"])
    @login_required
    def import_product_link():
        from html.parser import HTMLParser
        from html import unescape
        from urllib.parse import urlparse
        import re
        import json

        class MetaParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.meta = {}
                self.title_parts = []
                self.scripts = []
                self._in_title = False
                self._script_type = ""
                self._script_parts = []
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                tag = tag.lower()
                if tag == "meta":
                    key = (attrs.get("property") or attrs.get("name") or "").lower()
                    value = attrs.get("content", "").strip()
                    if key and value:
                        self.meta[key] = value
                elif tag == "title":
                    self._in_title = True
                elif tag == "script":
                    self._script_type = attrs.get("type", "").lower()
                    self._script_parts = []
            def handle_endtag(self, tag):
                tag = tag.lower()
                if tag == "title":
                    self._in_title = False
                elif tag == "script":
                    if self._script_parts:
                        self.scripts.append((self._script_type, "".join(self._script_parts)))
                    self._script_type = ""
                    self._script_parts = []
            def handle_data(self, data):
                if self._in_title:
                    self.title_parts.append(data)
                if self._script_type:
                    self._script_parts.append(data)

        def clean_text(value, limit=3000):
            value = unescape(str(value or ""))
            value = re.sub(r"<[^>]+>", " ", value)
            return re.sub(r"\s+", " ", value).strip()[:limit]

        def looks_generic(value):
            low = clean_text(value, 500).lower()
            generic_phrases = (
                "shopee brasil", "ofertas incríveis", "ofertas incriveis",
                "melhores preços do mercado", "melhores precos do mercado",
                "compre em menos de 30 segundos", "garantia shopee",
            )
            return not low or any(phrase in low for phrase in generic_phrases) or low == "shopee"

        def find_product_data(value, found):
            if isinstance(value, dict):
                kind = value.get("@type", "")
                kinds = kind if isinstance(kind, list) else [kind]
                if any(str(k).lower() == "product" for k in kinds):
                    if value.get("name") and not found.get("name"):
                        found["name"] = clean_text(value["name"], 180)
                    if value.get("description") and not found.get("notes"):
                        found["notes"] = clean_text(value["description"])
                    if value.get("category") and not found.get("category"):
                        category = value["category"]
                        found["category"] = clean_text(category if isinstance(category, str) else "", 80)
                    offers = value.get("offers", {})
                    offers = offers if isinstance(offers, list) else [offers]
                    for offer in offers:
                        if isinstance(offer, dict) and offer.get("price") is not None and not found.get("price"):
                            price = str(offer["price"]).replace(",", ".")
                            if re.fullmatch(r"\d+(?:\.\d{1,2})?", price):
                                try:
                                    if float(price) > 0:
                                        found["price"] = price.replace(".", ",")
                                except ValueError:
                                    pass
                for child in value.values():
                    find_product_data(child, found)
            elif isinstance(value, list):
                for child in value:
                    find_product_data(child, found)

        link = request.form.get("affiliate_link", "").strip()
        draft = {"name": "", "category": "", "price": "", "affiliate_link": link, "commission": "", "notes": ""}
        parsed = urlparse(link)
        host = (parsed.hostname or "").lower()
        allowed_hosts = ("shopee.com.br", "shope.ee")
        if parsed.scheme != "https" or not any(host == h or host.endswith("." + h) for h in allowed_hosts):
            flash("Cole um link HTTPS válido da Shopee. O link de afiliado será preservado exatamente como você enviou.", "error")
            categories = db.execute("""SELECT c.name, COUNT(p.id) AS product_count FROM categories c LEFT JOIN products p ON LOWER(TRIM(p.category)) = LOWER(TRIM(c.name)) GROUP BY c.id, c.name ORDER BY c.name COLLATE NOCASE""").fetchall()
            return render_template("product_form.html", product=None, product_photos=[], draft=draft, categories=categories)

        try:
            req = urllib.request.Request(
                link,
                headers={
                    "User-Agent": "Mozilla/5.0 (Linux; Android 15; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Cache-Control": "no-cache",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                final_url = response.geturl()
                final_host = (urlparse(final_url).hostname or "").lower()
                if not any(final_host == h or final_host.endswith("." + h) for h in allowed_hosts):
                    raise ValueError("redirect host not allowed")
                html = response.read(3_000_000).decode("utf-8", errors="replace")

            parser = MetaParser()
            parser.feed(html)
            title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or " ".join(parser.title_parts).strip()
            description = parser.meta.get("og:description") or parser.meta.get("twitter:description") or parser.meta.get("description", "")
            if title:
                title = re.sub(r"\s*[\-|]\s*Shopee.*$", "", clean_text(title, 500), flags=re.I).strip()
                if not looks_generic(title):
                    draft["name"] = title[:180]
            if description and not looks_generic(description):
                draft["notes"] = clean_text(description)

            # Algumas páginas entregam os dados do produto em JSON-LD, mesmo quando
            # o HTML visível é mínimo. Só usamos valores explicitamente presentes.
            structured = {"name": "", "category": "", "price": "", "notes": ""}
            for script_type, script_text in parser.scripts:
                if "ld+json" in script_type or script_text.lstrip().startswith(("{", "[")):
                    try:
                        find_product_data(json.loads(script_text), structured)
                    except (ValueError, TypeError):
                        pass
            for key in ("name", "category", "price", "notes"):
                if structured.get(key) and (key != "name" or looks_generic(draft["name"])):
                    draft[key] = structured[key]

            # Fallback conservador: extrai preço apenas de texto com formato monetário.
            # Não tenta adivinhar valores nem a comissão a partir de conteúdo genérico.
            visible_text = clean_text(re.sub(r"<[^>]+>", " ", html), 150000)
            if not draft["price"]:
                price_match = re.search(r"(?:R\$\s*|BRL\s*)(\d[\d.]*,\d{2})", visible_text, re.I)
                if price_match:
                    draft["price"] = price_match.group(1)

            commission_match = re.search(
                r"(?:comiss[aã]o|taxa\s+de\s+comiss[aã]o|commission)[^%]{0,100}?(\d{1,2}(?:[.,]\d{1,2})?)\s*%",
                visible_text, re.I
            )
            if commission_match:
                try:
                    pct = float(commission_match.group(1).replace(",", "."))
                    if 0 < pct <= 100:
                        draft["commission"] = str(pct).rstrip("0").rstrip(".")
                except ValueError:
                    pass

            imported = [draft[k] for k in ("name", "category", "price", "notes", "commission") if draft[k]]
            if imported:
                if not draft["name"]:
                    flash("A Shopee não revelou um nome de produto confiável. Não preenchi o título genérico da Shopee; digite o nome e confira os outros campos.", "warning")
                elif not draft["price"]:
                    flash("Encontrei alguns dados, mas o preço não ficou disponível no HTML recebido. Confira na página do produto antes de salvar.", "warning")
                else:
                    flash("Dados encontrados na página. Confira nome, preço e descrição antes de salvar; a comissão só é preenchida se estiver explícita.", "success")
                if not draft["commission"]:
                    flash("A taxa de comissão não apareceu de forma verificável; consulte a área de afiliados da Shopee e preencha manualmente.", "warning")
            else:
                flash("A Shopee bloqueou ou não incluiu os dados do produto no HTML recebido. O link de afiliado foi preservado; não inventei nome, preço nem comissão. Preencha manualmente ou tente um link direto do produto.", "error")
        except Exception:
            flash("Não consegui ler os dados desta página da Shopee. O link de afiliado foi preservado; a Shopee pode exigir JavaScript ou bloquear acesso automático. Tente um link direto do produto e confira os campos manualmente.", "error")
        return render_template("product_form.html", product=None, product_photos=[], draft=draft)

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
                if category:
                    db.execute("INSERT OR IGNORE INTO categories (name) VALUES (?)", (category,))
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
            categories = db.execute("""SELECT c.name, COUNT(p.id) AS product_count FROM categories c LEFT JOIN products p ON LOWER(TRIM(p.category)) = LOWER(TRIM(c.name)) GROUP BY c.id, c.name ORDER BY c.name COLLATE NOCASE""").fetchall()
            return render_template("product_form.html", product=product, product_photos=extras, categories=categories)
        finally:
            db.close()

    @app.post("/produtos/<int:product_id>/foto-principal/<int:photo_id>")
    @login_required
    def set_main_product_photo(product_id, photo_id):
        db = connect_db()
        try:
            product = db.execute("SELECT id, image_filename FROM products WHERE id=?", (product_id,)).fetchone()
            if product is None:
                abort(404)
            selected = db.execute(
                "SELECT id, filename FROM product_images WHERE id=? AND product_id=?",
                (photo_id, product_id),
            ).fetchone()
            if selected is None:
                abort(404)
            current_main = product["image_filename"]
            # Troca a foto principal com a foto adicional escolhida; nenhuma imagem é apagada.
            db.execute("UPDATE products SET image_filename=? WHERE id=?", (selected["filename"], product_id))
            if current_main:
                db.execute("UPDATE product_images SET filename=? WHERE id=? AND product_id=?", (current_main, photo_id, product_id))
            else:
                db.execute("DELETE FROM product_images WHERE id=? AND product_id=?", (photo_id, product_id))
            db.commit()
            flash("Foto principal atualizada. As outras fotos foram preservadas.", "success")
            return redirect(url_for("product_form", product_id=product_id))
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


    DEFAULT_CONTENT_SETTINGS = {
        "general_rules": "Use somente informações verdadeiras cadastradas no produto. Nunca invente características, descontos, avaliações, garantias ou benefícios. Nunca mencione comissão, percentual de comissão, ganhos do afiliado ou informações internas.",
        "visual_style": "Visual profissional, moderno, limpo e comercial; priorize a foto real do produto, boa legibilidade e aparência premium.",
        "colors": "Preto, branco e laranja; manter contraste alto e identidade visual consistente.",
        "story_rules": "Formato vertical 9:16. Usar a foto real do produto como referência. Deixar uma área livre e visível para adicionar o link do produto depois. Não desenhar QR code nem inventar link.",
        "feed_rules": "Formato vertical 3:4. Usar a foto real do produto como referência. Incluir a chamada: Esse e muitos outros no link no perfil.",
        "price_rules": "Exibir o preço cadastrado de forma legível, sem inventar descontos ou preço anterior. Se o preço estiver ausente, não inventar valor e avisar antes de gerar.",
        "text_rules": "Português do Brasil, texto curto, correto e fácil de ler. Não acrescentar informações que não estejam no cadastro ou nas instruções salvas.",
        "extra_instructions": ""
    }

    @app.route("/configuracoes-conteudo", methods=["GET", "POST"])
    @login_required
    def content_settings():
        db = connect_db()
        try:
            saved = {row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings").fetchall()}
            values = {key: saved.get(key, value) for key, value in DEFAULT_CONTENT_SETTINGS.items()}
            if request.method == "POST":
                values = {}
                for key, default in DEFAULT_CONTENT_SETTINGS.items():
                    values[key] = request.form.get(key, "").strip()
                    if not values[key] and key != "extra_instructions":
                        values[key] = default
                for key, value in values.items():
                    db.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
                db.commit()
                flash("Preferências de conteúdo salvas. As próximas publicações usarão estas regras.", "success")
                return redirect(url_for("content_settings"))
            return render_template("content_settings.html", settings=values)
        finally:
            db.close()


    @app.route("/conteudo/criar-com-ia", methods=["GET", "POST"])
    @login_required
    def create_content_ai():
        if request.method == "GET":
            db = connect_db()
            try:
                products_data = [dict(row) for row in db.execute(
                    "SELECT id, name, category, price, notes, image_filename FROM products ORDER BY name COLLATE NOCASE"
                ).fetchall()]
            finally:
                db.close()
            return render_template("content_ai.html", products=products_data, tipo=request.args.get("tipo", "story"))

        content_type = request.form.get("content_type", "story").strip().lower()
        product_id = request.form.get("product_id", type=int)
        revision = request.form.get("revision", "").strip()
        if content_type not in {"story", "post"}:
            abort(400)
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            flash("Falta configurar GEMINI_API_KEY no Termux. Nenhuma imagem foi gerada.", "error")
            return redirect(url_for("create_content_ai", tipo=content_type))

        db = connect_db()
        try:
            product = db.execute(
                "SELECT id, name, category, price, notes, image_filename, affiliate_link FROM products WHERE id=?",
                (product_id,),
            ).fetchone() if product_id else None
            if product is None:
                flash("Escolha um produto cadastrado.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))
            if product["price"] is None or not product["image_filename"]:
                flash("Este produto precisa ter preço e foto principal cadastrados antes da criação com IA.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))
            photos = [product["image_filename"]]
            photos += [r["filename"] for r in db.execute(
                "SELECT filename FROM product_images WHERE product_id=? ORDER BY id LIMIT 2", (product_id,)
            ).fetchall()]
            parts = []
            settings = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings").fetchall()}
            rules = {
                "gerais": settings.get("general_rules", ""),
                "estilo": settings.get("visual_style", ""),
                "cores": settings.get("colors", ""),
                "texto": settings.get("text_rules", ""),
                "preço": settings.get("price_rules", ""),
                "formato": settings.get("story_rules" if content_type == "story" else "feed_rules", ""),
                "instruções extras": settings.get("extra_instructions", ""),
            }
            ratio = "9:16" if content_type == "story" else "3:4"
            prompt = (
                "Crie uma arte promocional para Instagram usando as imagens de referência anexadas. "
                "Não altere a identidade do produto nem invente partes do produto. Gere uma única imagem. "
                "Inclua textos em português do Brasil, somente quando legíveis e corretos. "
                "Nunca mencione comissão, percentual de comissão, ganhos do afiliado ou informações internas. "
                "Não invente desconto, preço anterior, avaliação, garantia ou característica. "
                f"Produto: {product['name']}. Categoria: {product['category'] or 'não informada'}. "
                f"Preço cadastrado: R$ {product['price']:.2f}. Detalhes cadastrados: {product['notes'] or 'nenhum'}. "
                f"Formato obrigatório: {ratio}. Regras salvas pelo usuário: {json.dumps(rules, ensure_ascii=False)}. "
                f"Pedido de ajuste desta tentativa: {revision or 'primeira versão, sem ajustes adicionais'}. "
                "Para Stories, deixe uma área livre para inserir o link depois, sem desenhar link ou QR code. "
                "Para Feed, inclua exatamente a chamada 'Esse e muitos outros no link no perfil'. "
                "Priorize a foto real, composição limpa e boa leitura. Não adicione textos que não foram pedidos."
            )
            parts.append({"text": prompt})
            for filename in photos:
                path = upload_dir / filename
                if not path.is_file():
                    continue
                mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    continue
                raw = path.read_bytes()
                if len(raw) > 7 * 1024 * 1024:
                    continue
                parts.append({"inline_data": {"mime_type": mime, "data": base64.b64encode(raw).decode("ascii")}})
            if len(parts) == 1:
                flash("Não encontrei fotos de referência válidas para este produto.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))

            payload = {
                "contents": [{"parts": parts}],
                "generationConfig": {
                    "responseModalities": ["TEXT", "IMAGE"],
                    "imageConfig": {"aspectRatio": ratio}
                }
            }
            endpoint = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent?key=" + api_key
            req = urllib.request.Request(
                endpoint, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                app.logger.warning("Gemini API HTTP %s: %s", exc.code, detail)
                flash("O Gemini recusou a solicitação ou houve erro na API. Confira a chave, o acesso e a cota no Google AI Studio.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))
            except (urllib.error.URLError, TimeoutError):
                flash("Não foi possível conectar ao Gemini agora. Tente novamente em instantes.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))

            image_bytes = None
            caption_parts = []
            for candidate in result.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    if part.get("text"):
                        caption_parts.append(part["text"])
                    inline = part.get("inlineData") or part.get("inline_data")
                    if inline and inline.get("data") and (inline.get("mimeType") or inline.get("mime_type", "")).startswith("image/"):
                        image_bytes = base64.b64decode(inline["data"])
                        break
                if image_bytes:
                    break
            if not image_bytes:
                flash("O Gemini respondeu, mas não retornou uma imagem. Tente novamente ou simplifique as instruções.", "error")
                return redirect(url_for("create_content_ai", tipo=content_type))

            filename = uuid.uuid4().hex + ".png"
            (upload_dir / filename).write_bytes(image_bytes)
            caption = "\n".join(caption_parts).strip()
            if content_type == "post" and "link no perfil" not in caption.lower():
                caption = (caption + "\n\nEsse e muitos outros no link no perfil.").strip()
            db.execute(
                "INSERT INTO posts (product_id, caption, platform, status, content_type, image_filename) VALUES (?, ?, 'Instagram', 'Aguardando', ?, ?)",
                (product_id, caption, content_type, filename),
            )
            db.commit()
            flash("Imagem criada pelo Gemini e enviada para Aguardando aprovação. Revise antes de publicar.", "success")
            return redirect(url_for("content", tipo=content_type, status="Aguardando"))
        finally:
            db.close()

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