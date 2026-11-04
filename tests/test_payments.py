import pytest


def make_order(client, headers, qty=2):
    """Creates a product (price 100, stock 10) and an order for `qty` units.
    With qty=2 the order total is 200.00 and the order starts 'open'."""
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
    return r.json()


def pay(client, headers, order_id, amount):
    return client.post(
        f"/orders/{order_id}/payments",
        json={"order_id": order_id, "method": "CASH", "amount": amount},
        headers=headers,
    )


@pytest.mark.parametrize("amount", [500.0, 200.02])
def test_payment_above_balance_is_rejected(client, auth_headers, amount):
    order = make_order(client, auth_headers)
    assert order["total"] == 200.0

    r = pay(client, auth_headers, order["id"], amount)
    assert r.status_code == 400

    # Nothing was saved, and the order is untouched.
    after = client.get(f"/orders/{order['id']}", headers=auth_headers).json()
    assert after["status"] == "open"
    assert after["balance_due"] == 200.0
    payments = client.get(f"/orders/{order['id']}/payments", headers=auth_headers).json()
    assert payments == []


def test_exact_payment_completes_the_order(client, auth_headers):
    order = make_order(client, auth_headers)

    r = pay(client, auth_headers, order["id"], 200.0)
    assert r.status_code == 201

    after = client.get(f"/orders/{order['id']}", headers=auth_headers).json()
    assert after["status"] == "completed"
    assert after["balance_due"] == 0.0


def test_split_payments_cannot_exceed_the_total(client, auth_headers):
    order = make_order(client, auth_headers)

    assert pay(client, auth_headers, order["id"], 150.0).status_code == 201

    # 150 already paid, so only 50 is left. 100 must be refused.
    assert pay(client, auth_headers, order["id"], 100.0).status_code == 400

    after = client.get(f"/orders/{order['id']}", headers=auth_headers).json()
    assert after["status"] == "open"
    assert after["balance_due"] == 50.0
    payments = client.get(f"/orders/{order['id']}/payments", headers=auth_headers).json()
    assert len(payments) == 1

    # Paying the real remainder still works.
    assert pay(client, auth_headers, order["id"], 50.0).status_code == 201
    final = client.get(f"/orders/{order['id']}", headers=auth_headers).json()
    assert final["status"] == "completed"


@pytest.mark.parametrize("amount", [0, -5.0])
def test_zero_or_negative_payment_is_rejected(client, auth_headers, amount):
    order = make_order(client, auth_headers)

    r = pay(client, auth_headers, order["id"], amount)
    assert r.status_code == 400

    payments = client.get(f"/orders/{order['id']}/payments", headers=auth_headers).json()
    assert payments == []