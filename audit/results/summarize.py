import json, statistics as st
b = json.load(open("results/before.json"))
a = [json.load(open(f"results/after{i}.json")) for i in (1, 2, 3)]
rows = []
for k, v in b.items():
    p50 = st.median(x[k]["p50_ms"] for x in a); p95 = st.median(x[k]["p95_ms"] for x in a); q = round(st.median(x[k]["queries"] for x in a))
    rows.append((k, v["p50_ms"], p50, v["p95_ms"], p95, v["queries"], q, v["bytes"]))
rows.sort(key=lambda r: -r[1])
out = ["| Endpoint | p50 before (ms) | p50 after (ms) | change | p95 before | p95 after | SQL before | SQL after | response bytes |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
for k, b50, a50, b95, a95, bq, aq, by in rows:
    out.append(f"| `{k}` | {b50} | {a50} | {b50 / a50:.1f}x | {b95} | {a95} | {bq} | {aq} | {by} |")
open("results/benchmark-summary.md", "w").write("\n".join(out) + "\n")
print("\n".join(out))
