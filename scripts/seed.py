"""Repeatable data generation: 50 categories, 10k products, 10k orders, 30k items."""
import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.main import Base, engine, Category, Product, Order, OrderItem

def seed(size: int, reset: bool):
    random.seed(42)
    if reset:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    with Session(engine) as session:
        if session.query(Product).first():
            print("Banco já populado. Use --reset para recriar.")
            return
        session.bulk_insert_mappings(Category, [{"id": i, "name": f"Categoria {i:02d}"} for i in range(1, 51)])
        session.bulk_insert_mappings(Product, [{"id": i, "name": f"Produto {i:05d}", "price_cents": random.randint(100, 150000), "category_id": (i % 50) + 1} for i in range(1, size + 1)])
        baseline = datetime(2025, 1, 1)
        session.bulk_insert_mappings(Order, [{"id": i, "customer_name": f"Cliente {(i % 200):04d}", "created_at": baseline + timedelta(minutes=i)} for i in range(1, size + 1)])
        session.bulk_insert_mappings(OrderItem, [{"id": (i - 1) * 3 + j + 1, "order_id": i, "product_id": ((i * 7 + j) % size) + 1, "quantity": j + 1} for i in range(1, size + 1) for j in range(3)])
        session.commit()
    print(f"Criados: 50 categorias, {size} produtos, {size} pedidos e {3*size} itens.")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--size", type=int, default=10000)
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    if args.size < 1:
        p.error("--size deve ser positivo")
    seed(args.size, args.reset)
