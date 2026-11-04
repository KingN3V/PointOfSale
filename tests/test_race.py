import threading

from fastapi.testclient import TestClient

from pos.main import app

ROUNDS = 10


def make_product(client, headers, sku, stock):
    r = client.post(
        "/products/",
        json={
            "sku": sku,
            "name": f"Product {sku}",
            "price": 100.0,
            "cost_price": 60.0,
            "stock_quantity": stock,
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["id"]


def stock_of(client, headers, product_id):
    return client.get(f"/products/{product_id}", headers=headers).json()["stock_quantity"]


def movements_of(client, headers, product_id):
    rows = client.get(f"/products/{product_id}/stock-movements", headers=headers).json()
    return sorted((m["movement_type"], m["quantity_change"]) for m in rows)


def run_together(n, make_request):
    """Runs make_request(client) in n threads that are released at the same
    moment by a barrier. Each thread gets its own client. Returns the
    responses."""
    barrier = threading.Barrier(n, timeout=10)
    responses = [None] * n
    errors = []

    def worker(i):
        try:
            client = TestClient(app)
            barrier.wait()
            responses[i] = make_request(client)
        except Exception as exc:  # shows up in the assertion below
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    return responses


def test_two_simultaneous_orders_for_the_last_unit(client, auth_headers):
    for i in range(ROUNDS):
        product_id = make_product(client, auth_headers, f"LAST{i}", stock=1)

        def order(c):
            return c.post(
                "/orders/",
                json={"customer_id": None, "items": [{"product_id": product_id, "quantity": 1}]},
                headers=auth_headers,
            )

        responses = run_together(2, order)

        assert sorted(r.status_code for r in responses) == [201, 400], f"round {i}"
        assert stock_of(client, auth_headers, product_id) == 0, f"round {i}"
        assert movements_of(client, auth_headers, product_id) == [
            ("initial_stock", 1),
            ("sale", -1),
        ], f"round {i}"


def test_five_simultaneous_orders_for_three_units(client, auth_headers):
    for i in range(ROUNDS):
        product_id = make_product(client, auth_headers, f"THREE{i}", stock=3)

        def order(c):
            return c.post(
                "/orders/",
                json={"customer_id": None, "items": [{"product_id": product_id, "quantity": 1}]},
                headers=auth_headers,
            )

        responses = run_together(5, order)

        assert sorted(r.status_code for r in responses) == [201, 201, 201, 400, 400], f"round {i}"
        assert stock_of(client, auth_headers, product_id) == 0, f"round {i}"


def test_two_simultaneous_cancels_restore_stock_once(client, auth_headers):
    for i in range(ROUNDS):
        product_id = make_product(client, auth_headers, f"CANCEL{i}", stock=10)
        order = client.post(
            "/orders/",
            json={"customer_id": None, "items": [{"product_id": product_id, "quantity": 2}]},
            headers=auth_headers,
        ).json()
        assert stock_of(client, auth_headers, product_id) == 8

        def cancel(c):
            return c.post(f"/orders/{order['id']}/cancel", headers=auth_headers)

        responses = run_together(2, cancel)

        assert sorted(r.status_code for r in responses) == [200, 400], f"round {i}"
        assert stock_of(client, auth_headers, product_id) == 10, f"round {i}"
        assert movements_of(client, auth_headers, product_id) == sorted([
            ("initial_stock", 10),
            ("sale", -2),
            ("sale_cancelled", 2),
        ]), f"round {i}"