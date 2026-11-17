import os
os.environ["DATABASE_URL"] = "sqlite:///./a2_test.db"
os.environ["CACHE_TTL"] = "0.1"
from fastapi.testclient import TestClient
from scripts.seed import seed
from app.main import app

client = TestClient(app)

def setup_module():
    seed(100, True)

def test_cache_invalidation():
    client.delete("/api/cache")
    first = client.get("/api/products/10/cache").json()
    second = client.get("/api/products/10/cache").json()
    assert first["source"] == "database" and second["source"] == "cache"
    client.patch("/api/products/10", json={"price_cents": 1234})
    third = client.get("/api/products/10/cache").json()
    assert third["source"] == "database" and third["product"]["price_cents"] == 1234

def test_loading_queries():
    lazy = client.get("/api/orders/lazy?limit=10").json()
    eager = client.get("/api/orders/eager?limit=10").json()
    optimized = client.get("/api/orders/optimized?limit=10").json()
    assert lazy["sql_queries"] == 11
    assert eager["sql_queries"] == 1
    assert optimized["sql_queries"] == 2
    assert lazy["item_count"] == eager["item_count"] == optimized["item_count"]

def test_explain_index():
    client.delete("/api/index")
    before = str(client.get("/api/index/explain").json()["plan"])
    client.post("/api/index/create")
    after = str(client.get("/api/index/explain").json()["plan"])
    assert "idx_orders_customer_date" not in before
    assert "idx_orders_customer_date" in after
