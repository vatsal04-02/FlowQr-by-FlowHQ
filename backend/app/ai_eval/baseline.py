"""Record a live benchmark run as a regression baseline (outputs + score floors) for tests/test_ai_regression.py.

  python -m app.ai_eval.baseline --run docs/ai-eval/<run>.json --model gemini-3.5-flash-lite --out tests/ai_baselines

Writes <model>.current.json (and <model>.legacy.json when the run has that variant). Floors are the measured averages minus a small tolerance, so ordinary
noise in rescoring does not fail the build but a real regression does."""
from __future__ import annotations

import argparse
import json
import os

from app.ai_eval import runner
from app.ai_eval.dataset import ALL_CASES

TOL = 0.01


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run_ = runner.rescore(json.load(open(a.run, encoding="utf-8"))["run"])
    os.makedirs(a.out, exist_ok=True)
    for r in run_["runs"]:
        if r["model"] != a.model:
            continue
        outs, floors = [], {}
        for task in ("reply", "post", "description"):
            rows = [x for x in r["rows"] if x["task"] == task and x.get("metrics")]
            if not rows:
                continue
            outs += [{"case": x["case"], "task": task, "text": x["text"]} for x in rows]
            floors[task] = {"composite": round(sum(x["metrics"]["composite"] for x in rows) / len(rows) - TOL, 3),
                            "clean_rate": round(max(0.0, sum(1 for x in rows if x["metrics"]["clean"]) / len(rows) - 0.08), 3),
                            "max_unsupported_claims": sum(x["metrics"]["unsupported_claims"] for x in rows) + 1}
        path = os.path.join(a.out, f"{a.model}.{r['variant']}.json")
        json.dump({"model": a.model, "variant": r["variant"], "recorded": run_.get("started"), "metric_version": 2, "floors": floors, "outputs": outs}, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", path, {t: (f["composite"], f["clean_rate"]) for t, f in floors.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
