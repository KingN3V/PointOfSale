from pos.database import engine


def test_uses_the_test_database():
    assert engine.url.database == "pos_test"


def test_healthy(client):
    assert client.get("/healthy").status_code == 200


def test_create_and_list_product(client, auth_headers):
    body = {
        "sku": "S1",
        "name": "Maize seed",
        "price": 100.0,
        "cost_price": 60.0,
        "stock_quantity": 10,
    }
    r = client.post("/products/", json=body, headers=auth_headers)
    assert r.status_code == 201

    r = client.get("/products/", headers=auth_headers)
    assert r.status_code == 200
    assert [p["sku"] for p in r.json()] == ["S1"]