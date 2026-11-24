import json
b = [r for r in json.load(open("perf-local.json")) if r["page"].startswith("/") and r["status"] == 200]
a = [r for r in json.load(open("perf-local-final.json")) if r["status"] == 200]
pages = ["/overview", "/gbp/reviews", "/gbp/posts", "/gbp/campaigns", "/ai/today", "/gbp/cards", "/seo", "/growth", "/settings/team", "/settings/billing", "/whatsapp/inbox"]
def f(rows, p, key, w=None): 
    v = [r[key] for r in rows if r["page"] == p and (w is None or r["width"] == w)]
    return v
out = ["| Page | API calls @360 before | after | worst layout shift (any width) before | after | horizontal page overflow (widths) before | after |", "|---|---:|---:|---:|---:|---|---|"]
for p in pages:
    ab, aa = f(b, p, "apiCalls", 360)[0], f(a, p, "apiCalls", 360)[0]
    db = sum(int(x.split(" x")[1]) - 1 for x in f(b, p, "dupApi", 360)[0]) ; da = sum(int(x.split(" x")[1]) - 1 for x in f(a, p, "dupApi", 360)[0])
    cb, ca = max(f(b, p, "cls")), max(f(a, p, "cls"))
    ob = [r["width"] for r in b if r["page"] == p and r["docOverflow"]]; oa = [r["width"] for r in a if r["page"] == p and r["docOverflow"]]
    out.append(f"| `{p}` | {ab} | {aa} | {cb} | {ca} | {ob or 'none'} | {oa or 'none'} |")
open("frontend-summary.md", "w").write("\n".join(out) + "\n"); print("\n".join(out))
