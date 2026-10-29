import re

from app import create_app


def make_app(tmp_path):
    return create_app({
        "TESTING": True,
        "SECRET_KEY": "test-only-secret",
        "DATABASE": str(tmp_path / "test.sqlite3"),
    })


def csrf(client, path):
    response = client.get(path)
    assert response.status_code == 200
    match = re.search(
        r'name="_csrf_token" value="([^"]+)"',
        response.get_data(as_text=True),
    )
    assert match, "form must contain CSRF token"
    return match.group(1)


def test_health_endpoint(tmp_path):
    app = make_app(tmp_path)
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_setup_creates_first_user_and_protects_dashboard(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"] or "/configurar" in response.headers["Location"]

    token = csrf(client, "/configurar")
    response = client.post("/configurar", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
        "confirmation": "senha-forte-de-teste-123",
    }, follow_redirects=True)
    assert response.status_code == 200
    assert "Produtos cadastrados" in response.get_data(as_text=True)

    # First-run setup cannot be used to create another account.
    response = client.get("/configurar")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_rejects_wrong_password_and_accepts_correct_password(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()
    token = csrf(client, "/configurar")
    client.post("/configurar", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
        "confirmation": "senha-forte-de-teste-123",
    })

    client.post("/logout", data={"_csrf_token": csrf(client, "/")})
    token = csrf(client, "/login")
    bad = client.post("/login", data={
        "_csrf_token": token, "username": "gabriel", "password": "errada"
    })
    assert "Usuário ou senha incorretos" in bad.get_data(as_text=True)

    token = csrf(client, "/login")
    good = client.post("/login", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
    }, follow_redirects=True)
    assert good.status_code == 200
    assert "Produtos cadastrados" in good.get_data(as_text=True)


def test_post_without_csrf_is_rejected(tmp_path):
    app = make_app(tmp_path)
    response = app.test_client().post("/login", data={
        "username": "anyone", "password": "anything"
    })
    assert response.status_code == 400


def test_catalog_creates_product_with_separate_affiliate_link(tmp_path):
    app = make_app(tmp_path)
    client = app.test_client()

    token = csrf(client, "/configurar")
    client.post("/configurar", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
        "confirmation": "senha-forte-de-teste-123",
    })

    token = csrf(client, "/produtos/novo")
    response = client.post("/produtos/novo", data={
        "_csrf_token": token,
        "name": "Tênis de corrida",
        "category": "Corrida",
        "price": "119,80",
        "affiliate_link": "https://shopee.com.br/teste-afiliado",
        "commission": "8,50",
        "notes": "Produto de teste",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert "Tênis de corrida" in response.get_data(as_text=True)

    db = app.config["DATABASE"]
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        product = conn.execute(
            "SELECT name, price, affiliate_link, commission FROM products"
        ).fetchone()
        assert product == (
            "Tênis de corrida", 119.8,
            "https://shopee.com.br/teste-afiliado", 8.5
        )
    finally:
        conn.close()


def test_catalog_accepts_multiple_product_photos(tmp_path):
    from io import BytesIO
    import sqlite3

    app = make_app(tmp_path)
    client = app.test_client()
    token = csrf(client, "/configurar")
    client.post("/configurar", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
        "confirmation": "senha-forte-de-teste-123",
    })

    token = csrf(client, "/produtos/novo")
    response = client.post("/produtos/novo", data={
        "_csrf_token": token,
        "name": "Produto com fotos",
        "category": "Teste",
        "price": "25,00",
        "affiliate_link": "https://shopee.com.br/produto-teste",
        "photos": [
            (BytesIO(b"fake-image-one"), "foto1.jpg"),
            (BytesIO(b"fake-image-two"), "foto2.png"),
            (BytesIO(b"fake-image-three"), "foto3.webp"),
        ],
    }, content_type="multipart/form-data", follow_redirects=True)

    assert response.status_code == 200
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        main_photo = conn.execute(
            "SELECT image_filename FROM products WHERE name=?",
            ("Produto com fotos",)
        ).fetchone()[0]
        extra_count = conn.execute(
            "SELECT COUNT(*) FROM product_images WHERE product_id=("
            "SELECT id FROM products WHERE name=?)",
            ("Produto com fotos",)
        ).fetchone()[0]
        assert main_photo
        assert extra_count == 2
    finally:
        conn.close()



def login_first_user(client):
    token = csrf(client, "/configurar")
    client.post("/configurar", data={
        "_csrf_token": token,
        "username": "gabriel",
        "password": "senha-forte-de-teste-123",
        "confirmation": "senha-forte-de-teste-123",
    })


def test_shopee_search_page_requires_login(tmp_path):
    app = make_app(tmp_path)
    response = app.test_client().get("/produtos/buscar-shopee")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_shopee_search_page_renders_without_credentials_and_does_not_save_products(tmp_path, monkeypatch):
    from shopee_affiliate import ShopeeAffiliateClient, ShopeeAPIError

    app = make_app(tmp_path)
    client = app.test_client()
    login_first_user(client)
    monkeypatch.setattr(
        ShopeeAffiliateClient,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(ShopeeAPIError("API não configurada para teste")),
    )
    token = csrf(client, "/produtos/buscar-shopee")
    response = client.post(
        "/produtos/buscar-shopee",
        data={"_csrf_token": token, "keyword": "tênis de corrida"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "tênis de corrida" in response.get_data(as_text=True)
    assert "API não configurada para teste" in response.get_data(as_text=True)
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    finally:
        conn.close()


def test_shopee_search_page_renders_mocked_offers_without_saving(tmp_path, monkeypatch):
    from shopee_affiliate import ShopeeAffiliateClient

    app = make_app(tmp_path)
    client = app.test_client()
    login_first_user(client)
    monkeypatch.setattr(
        ShopeeAffiliateClient,
        "request",
        lambda *args, **kwargs: {
            "productOfferV2": {
                "nodes": [{
                    "itemId": "12345",
                    "productName": "Tênis de teste",
                    "shopName": "Loja teste",
                    "price": 119.8,
                    "imageUrl": "https://example.com/tenis.jpg",
                    "offerLink": "https://example.com/oferta",
                    "productLink": "https://example.com/produto",
                    "commissionRate": "8%",
                    "sales": 10,
                    "ratingStar": 4.8,
                    "priceDiscountRate": 15,
                }],
                "pageInfo": {"page": 1, "limit": 10, "hasNextPage": False},
            }
        },
    )
    token = csrf(client, "/produtos/buscar-shopee")
    response = client.post(
        "/produtos/buscar-shopee",
        data={"_csrf_token": token, "keyword": "tênis"},
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Tênis de teste" in html
    assert "119,80" in html
    assert "Abrir link de oferta" in html
    import sqlite3
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0
    finally:
        conn.close()
