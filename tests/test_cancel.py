def make_order(client, headers, qty=2):
    """Creates a product (price 100, stock 10) and an order for `qty` units.
    Returns (order, product_id). With qty=2, stock drops to 8 and the order
    total is 200.00."""
    product = client.post(
        "/products/",
        json={
            "sku": "P1",
            "name": "Maize seed",
            "price": 100.0,
            "cost_price": 60.0,
            "stock_quantity": 10,
        },
        headers=headers,
    ).json()

    r = client.post(
        "/orders/",
        json={"customer_id": None, "items": [{"product_id": product["id"], "quantity": qty}]},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json(), product["id"]


def stock_of(client, headers, product_id):
    return client.get(f"/products/{product_id}", headers=headers).json()["stock_quantity"]


def movements_of(client, headers, product_id):
    rows = client.get(f"/products/{product_id}/stock-movements", headers=headers).json()
    return sorted((m["movement_type"], m["quantity_change"]) for m in rows)


def test_cancel_puts_stock_back(client, auth_headers):
    order, product_id = make_order(client, auth_headers)
    assert stock_of(client, auth_headers, product_id) == 8

    r = client.post(f"/orders/{order['id']}/cancel", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert stock_of(client, auth_headers, product_id) == 10


def test_second_cancel_is_refused_and_stock_not_restored_twice(client, auth_headers):
    order, product_id = make_order(client, auth_headers)

    assert client.post(f"/orders/{order['id']}/cancel", headers=auth_headers).status_code == 200
    assert client.post(f"/orders/{order['id']}/cancel", headers=auth_headers).status_code == 400

    # 10, not 12.
    assert stock_of(client, auth_headers, product_id) == 10


def test_cancel_logs_exactly_one_sale_cancelled_movement(client, auth_headers):
    order, product_id = make_order(client, auth_headers)

    client.post(f"/orders/{order['id']}/cancel", headers=auth_headers)
    client.post(f"/orders/{order['id']}/cancel", headers=auth_headers)  # refused

    assert movements_of(client, auth_headers, product_id) == sorted([
        ("initial_stock", 10),
        ("sale", -2),
        ("sale_cancelled", 2),
    ])


def test_completed_order_cannot_be_cancelled(client, auth_headers):
    order, product_id = make_order(client, auth_headers)

    r = client.post(
        f"/orders/{order['id']}/payments",
        json={"order_id": order["id"], "method": "CASH", "amount": 200.0},
        headers=auth_headers,
    )
    assert r.status_code == 201

    assert client.post(f"/orders/{order['id']}/cancel", headers=auth_headers).status_code == 400

    # Stock stays deducted, and the order is still completed.
    assert stock_of(client, auth_headers, product_id) == 8
    after = client.get(f"/orders/{order['id']}", headers=auth_headers).json()
    assert after["status"] == "completed"