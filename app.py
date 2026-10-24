"""Base inicial da Central de Afiliados. Não publicar na internet ainda."""
import os
from pathlib import Path

from flask import Flask, render_template


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("CENTRAL_SECRET_KEY"),
        DATABASE=os.environ.get(
            "CENTRAL_DATABASE",
            str(Path(app.instance_path) / "central.sqlite3"),
        ),
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    @app.get("/")
    def dashboard():
        return render_template("dashboard.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "application": "central-afiliados-next"}

    return app


if __name__ == "__main__":
    # Apenas desenvolvimento local. O servidor de desenvolvimento não é para produção.
    application = create_app()
    if not application.config.get("SECRET_KEY"):
        raise RuntimeError(
            "Defina CENTRAL_SECRET_KEY no ambiente antes de iniciar a aplicação."
        )
    application.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
