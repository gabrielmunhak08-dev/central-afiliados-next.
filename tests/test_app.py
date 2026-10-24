from app import create_app


def test_health_endpoint():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret"})
    client = app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_dashboard_renders():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-secret"})
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert "Central de Afiliados" in response.get_data(as_text=True)
