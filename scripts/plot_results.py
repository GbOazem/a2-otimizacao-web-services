import csv
from collections import defaultdict
from pathlib import Path
import matplotlib.pyplot as plt
root = Path(__file__).resolve().parents[1]
with (root / "results" / "summary.csv").open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))
series = defaultdict(list)
for row in rows:
    series[row["scenario"]].append((int(row["users"]), float(row["p95_ms"])))
for label, items in series.items():
    xs, ys = zip(*sorted(items))
    plt.plot(xs, ys, marker="o", label=label)
plt.xlabel("Usuários virtuais simultâneos")
plt.ylabel("Latência p95 (ms)")
plt.title("A2 — Comparação de estratégias")
plt.legend()
plt.tight_layout()
plt.savefig(root / "results" / "p95_comparison.png", dpi=160)
print("Gráfico salvo em results/p95_comparison.png")
