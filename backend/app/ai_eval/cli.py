"""CLI for the AI evaluation (registered in app/cli.py).

  python -m app.cli ai-eval --models gemini-3.5-flash,gemini-3.5-flash-lite --variants legacy,current --tasks reply,post,description,review_draft \
        --price gemini-3.5-flash=0.30,2.50 --out docs/ai-eval
  python -m app.cli ai-eval-human --run docs/ai-eval/<run>.json --ratings ratings.csv      # compare the automatic scores with a person's ratings

`ai-eval` calls the real model with the invented benchmark business text (never customer data) and costs real, small, money. It needs GEMINI_API_KEY.
It also writes <run>.csv, a rating sheet for a human reviewer: columns usable_as_is (yes/no) and score (1-5) are left empty for them to fill in."""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
from datetime import datetime

METRICS = ["composite", "factual", "compliance", "relevance", "naturalness", "repetition", "language", "brand_voice", "helpfulness", "local", "quality_score"]


def add_commands(sub) -> None:
    p = sub.add_parser("ai-eval", help="run the AI quality benchmark (calls the real model; small cost)")
    p.add_argument("--models", default="")
    p.add_argument("--variants", default="current", help="legacy,current")
    p.add_argument("--tasks", default="reply,post,description,review_draft")
    p.add_argument("--biz", help="one business key only (physio, dental, salon, restaurant, gym, retail, coaching)")
    p.add_argument("--limit", type=int)
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--rpm", type=float, default=12, help="requests per minute to send (stay under the key's limit; a rate-limited call would count against the model)")
    p.add_argument("--thinking", default="minimal", help="Gemini thinking level ('' to omit)")
    p.add_argument("--price", action="append", default=[], metavar="MODEL=IN,OUT", help="USD per 1M tokens, from the provider's price list; without it only tokens are reported")
    p.add_argument("--out", default="docs/ai-eval")
    rs = sub.add_parser("ai-eval-rescore", help="recompute the metrics of a saved run with the current metric code (no model calls)")
    rs.add_argument("--run", required=True)
    rs.add_argument("--price", action="append", default=[])
    h = sub.add_parser("ai-eval-human", help="compare automatic scores with a human reviewer's ratings")
    h.add_argument("--run", required=True)
    h.add_argument("--ratings", required=True)


def _prices(items: list[str]) -> dict:
    out = {}
    for it in items:
        m, v = it.split("=", 1)
        a, b = v.split(",")
        out[m] = (float(a), float(b))
    return out


def markdown(summary: dict) -> str:
    L = ["| model | variant | task | n | failed | clean% | composite | factual | compliance | relevance | natural | repetition | language | helpful | claims/out | p50 ms | calls | tok in/out | $/out | $/clean |", "|" + "---|" * 20]
    f = lambda v: "" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))  # noqa: E731
    for r in summary["rows"]:
        L.append(f"| {r['model']} | {r['variant']} | {r['task']} | {r['n']} | {r['failed']} | {r['clean_rate'] * 100:.0f}% | {f(r['composite'])} | {f(r['factual'])} | {f(r['compliance'])} | {f(r['relevance'])} | "
                 f"{f(r['naturalness'])} | {f(r['repetition'])} | {f(r['language'])} | {f(r['helpfulness'])} | {r['unsupported_claims_per_output']} | {r['latency_p50_ms']} | {r['calls_per_output']} | "
                 f"{r['tokens_in_per_output']}/{r['tokens_out_per_output']} | {f(r['cost_per_output_usd']) if r['cost_per_output_usd'] is None else '%.5f' % r['cost_per_output_usd']} | "
                 f"{'' if r['cost_per_clean_output_usd'] is None else '%.5f' % r['cost_per_clean_output_usd']} |")
    return "\n".join(L)


def write_sheet(run_: dict, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["case", "model", "variant", "task", "language", "output", "usable_as_is (yes/no)", "score (1-5)", "notes"])
        for r in run_["runs"]:
            for x in r["rows"]:
                w.writerow([x["case"], r["model"], r["variant"], x["task"], x["lang"], x["text"], "", "", ""])


def run_eval(args) -> int:
    from app.ai_eval import runner
    models = [m for m in args.models.split(",") if m] or [runner.settings.gemini_model]
    variants = [v for v in args.variants.split(",") if v]
    tasks = [t for t in args.tasks.split(",") if t]
    print(f"AI evaluation: models={models} variants={variants} tasks={tasks}" + (f" biz={args.biz}" if args.biz else "") + (f" limit={args.limit}" if args.limit else ""))
    res = runner.run(models, variants, tasks, limit=args.limit, workers=args.workers, thinking=args.thinking or None, biz=args.biz, rpm=args.rpm)
    summ = runner.summarise(res, _prices(args.price))
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = os.path.join(args.out, f"run-{stamp}")
    runner.save(res, summ, base + ".json")
    write_sheet(res, base + ".csv")
    with open(base + ".md", "w", encoding="utf-8") as fh:
        fh.write(markdown(summ) + "\n")
    print(markdown(summ))
    print(f"\nSaved {base}.json (full outputs and metrics), {base}.md, and {base}.csv (rating sheet for a human reviewer)")
    return 0


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    for pos, i in enumerate(order):
        r[i] = pos + 1
    return r


def human(args) -> int:
    run_ = json.load(open(args.run, encoding="utf-8"))["run"]
    auto = {(r["model"], r["variant"], x["case"]): x["metrics"]["composite"] for r in run_["runs"] for x in r["rows"] if x.get("metrics")}
    pairs, yes, total = [], {}, {}
    for row in csv.DictReader(open(args.ratings, encoding="utf-8")):
        key = (row["model"], row["variant"], row["case"])
        s, u = (row.get("score (1-5)") or "").strip(), (row.get("usable_as_is (yes/no)") or "").strip().lower()
        if key in auto and s.isdigit():
            pairs.append((auto[key], int(s)))
        if u in ("yes", "no"):
            mk = (row["model"], row["variant"])
            total[mk] = total.get(mk, 0) + 1
            yes[mk] = yes.get(mk, 0) + (u == "yes")
    if len(pairs) >= 5:
        a, b = _rank([p[0] for p in pairs]), _rank([p[1] for p in pairs])
        ma, mb = statistics.mean(a), statistics.mean(b)
        den = (sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b)) ** 0.5
        rho = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / den if den else 0.0
        print(f"Spearman correlation between the automatic composite and the human score: {rho:.2f} over {len(pairs)} rated outputs")
    else:
        print("Fewer than 5 outputs have a human score: nothing to correlate yet.")
    for mk, n in total.items():
        print(f"human 'usable as is': {mk[0]} / {mk[1]}: {yes[mk]}/{n} = {yes[mk] / n:.0%}")
    return 0


def rescore_cmd(args) -> int:
    from app.ai_eval import runner
    data = json.load(open(args.run, encoding="utf-8"))
    run_ = runner.rescore(data["run"])
    summ = runner.summarise(run_, _prices(args.price))
    runner.save(run_, summ, args.run)
    print(markdown(summ))
    return 0


def run(args) -> int:
    return run_eval(args) if args.cmd == "ai-eval" else rescore_cmd(args) if args.cmd == "ai-eval-rescore" else human(args)
