"""A2: REST API for demonstrating cache, ORM loading strategies, and indexes."""

import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, create_engine, event, select, text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    joinedload,
    mapped_column,
    relationship,
    selectinload,
)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./a2.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)


class Base(DeclarativeBase):
    pass


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    products: Mapped[list["Product"]] = relationship(back_populates="category", lazy="select")


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    category: Mapped[Category] = relationship(back_populates="products", lazy="select")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="product", lazy="select")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_name: Mapped[str] = mapped_column(String(140), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", lazy="select")


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    order: Mapped[Order] = relationship(back_populates="items", lazy="select")
    product: Mapped[Product] = relationship(back_populates="order_items", lazy="select")


Base.metadata.create_all(engine)
app = FastAPI(title="UVA A2 — Otimização de Web Services", version="1.0.0")
from fastapi.responses import RedirectResponse

@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/docs")

# Cache local de memória, adequado à demonstração com um processo.
CACHE_TTL = float(os.getenv("CACHE_TTL", "30"))
_cache: dict[int, tuple[float, dict]] = {}
_cache_lock = threading.Lock()
_cache_stats = {"hits": 0, "misses": 0, "invalidations": 0}
_sql_local = threading.local()


@event.listens_for(engine, "before_cursor_execute")
def _count_queries(conn, cursor, statement, parameters, context, executemany):
    if getattr(_sql_local, "active", False):
        _sql_local.count += 1


@contextmanager
def count_queries():
    previous_active = getattr(_sql_local, "active", False)
    previous_count = getattr(_sql_local, "count", 0)
    _sql_local.active = True
    _sql_local.count = 0
    try:
        yield lambda: _sql_local.count
    finally:
        _sql_local.active = previous_active
        if previous_active:
            _sql_local.count += previous_count
        else:
            _sql_local.count = previous_count


def product_dict(p: Product) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "price_cents": p.price_cents,
        "category_id": p.category_id,
    }


def get_product(product_id: int) -> dict:
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        return product_dict(product)


@app.get("/api/products/{product_id}/no-cache")
def product_no_cache(product_id: int):
    with count_queries() as queries:
        result = get_product(product_id)
        return {"source": "database", "sql_queries": queries(), "product": result}


@app.get("/api/products/{product_id}/cache")
def product_cache(product_id: int):
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(product_id)
        if entry and entry[0] > now:
            _cache_stats["hits"] += 1
            return {"source": "cache", "sql_queries": 0, "product": entry[1]}
        _cache.pop(product_id, None)
        _cache_stats["misses"] += 1

    with count_queries() as queries:
        result = get_product(product_id)
        n_queries = queries()

    with _cache_lock:
        _cache[product_id] = (time.monotonic() + CACHE_TTL, result)
    return {"source": "database", "sql_queries": n_queries, "product": result}


class PriceUpdate(BaseModel):
    price_cents: int = Field(ge=0)


@app.patch("/api/products/{product_id}")
def update_product(product_id: int, body: PriceUpdate):
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if product is None:
            raise HTTPException(status_code=404, detail="Produto não encontrado")
        product.price_cents = body.price_cents
        session.commit()
        data = product_dict(product)

    with _cache_lock:
        if _cache.pop(product_id, None) is not None:
            _cache_stats["invalidations"] += 1
    return {"updated": True, "cache_invalidated": True, "product": data}


@app.get("/api/cache/stats")
def cache_stats():
    with _cache_lock:
        return {**_cache_stats, "entries": len(_cache), "ttl_seconds": CACHE_TTL}


@app.delete("/api/cache")
def reset_cache():
    with _cache_lock:
        _cache.clear()
    return {"cleared": True}


def serialize_orders(orders):
    return [
        {
            "id": order.id,
            "customer_name": order.customer_name,
            "items": [
                {"id": item.id, "product_id": item.product_id, "quantity": item.quantity}
                for item in order.items
            ],
        }
        for order in orders
    ]


# IMPORTANTE: a rota fixa /search deve ser declarada ANTES de /{strategy}.
@app.get("/api/orders/search")
def search_orders(
    customer_name: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
):
    started = time.perf_counter()
    with Session(engine) as session:
        orders = session.scalars(
            select(Order)
            .where(Order.customer_name == customer_name)
            .order_by(Order.created_at.desc())
            .limit(limit)
        ).all()
        return {
            "count": len(orders),
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            "orders": [
                {
                    "id": order.id,
                    "customer_name": order.customer_name,
                    "created_at": order.created_at.isoformat(),
                }
                for order in orders
            ],
        }


@app.get("/api/orders/{strategy}")
def orders_by_strategy(strategy: str, limit: int = Query(20, ge=1, le=300)):
    if strategy not in {"lazy", "eager", "optimized"}:
        raise HTTPException(status_code=400, detail="Use lazy, eager ou optimized")

    started = time.perf_counter()
    with count_queries() as queries:
        with Session(engine) as session:
            stmt = select(Order).order_by(Order.id).limit(limit)
            if strategy == "eager":
                # JOIN em uma única consulta SQL.
                stmt = stmt.options(joinedload(Order.items))
                orders = session.scalars(stmt).unique().all()
            elif strategy == "optimized":
                # SELECT IN: em geral, duas consultas para este volume.
                stmt = stmt.options(selectinload(Order.items))
                orders = session.scalars(stmt).all()
            else:
                # LAZY: demonstra o problema N+1.
                orders = session.scalars(stmt).all()
            result = serialize_orders(orders)
        n_queries = queries()

    return {
        "strategy": strategy,
        "orders": result,
        "order_count": len(result),
        "item_count": sum(len(order["items"]) for order in result),
        "sql_queries": n_queries,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
    }


@app.get("/api/index/explain")
def index_explain(customer_name: str = "Cliente 0010"):
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            plan = conn.execute(
                text(
                    "EXPLAIN QUERY PLAN SELECT id FROM orders "
                    "WHERE customer_name = :name ORDER BY created_at DESC LIMIT 50"
                ),
                {"name": customer_name},
            ).all()
            return {"database": "sqlite", "plan": [list(row) for row in plan]}

        if engine.dialect.name == "postgresql":
            plan = conn.execute(
                text(
                    "EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) SELECT id FROM orders "
                    "WHERE customer_name = :name ORDER BY created_at DESC LIMIT 50"
                ),
                {"name": customer_name},
            ).all()
            return {"database": "postgresql", "plan": [row[0] for row in plan]}

    raise HTTPException(status_code=400, detail="EXPLAIN implementado para SQLite e PostgreSQL")


@app.post("/api/index/create")
def index_create():
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_orders_customer_date "
                "ON orders(customer_name, created_at DESC)"
            )
        )
    return {"index": "idx_orders_customer_date", "created_if_missing": True}


@app.delete("/api/index")
def index_drop():
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX IF EXISTS idx_orders_customer_date"))
    return {"index": "idx_orders_customer_date", "dropped_if_exists": True}


@app.get("/health")
def health():
    return {"status": "ok"}
