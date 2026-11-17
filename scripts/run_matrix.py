"""Execute same load across endpoints and user levels. Server must be running."""
import csv
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
results = root / "results"
results.mkdir(exist_ok=True)
scenarios = ["no-cache", "cache", "lazy", "eager", "optimized"]
users = [10, 50, 100, 200]
rows = []
for scenario in scenarios:
    for n in users:
        path = results / f"{scenario}_{n}.json"
        command = [sys.executable, str(root / "scripts" / "load_test.py"), "--scenario", scenario,
                   "--users", str(n), "--duration", "10", "--output", str(path)]
        print(f"Executando {scenario}, {n} usuários", flush=True)
        subprocess.run(command, check=True)
        rows.append(json.loads(path.read_text(encoding="utf-8")))
with (results / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
print("Resultados em results/summary.csv")
