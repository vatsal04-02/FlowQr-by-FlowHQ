import re, sys, glob, os
pats = {
 "openai key (sk-proj/sk-...)": r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}",
 "openrouter key": r"sk-or-[A-Za-z0-9\-_]{20,}",
 "google api key (AIza...)": r"AIza[0-9A-Za-z_\-]{30,}",
 "google oauth client secret (GOCSPX-)": r"GOCSPX-[0-9A-Za-z_\-]{10,}",
 "aws access key": r"AKIA[0-9A-Z]{16}",
 "private key block": r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
 "slack/github/stripe-style token": r"(?:xox[baprs]-[0-9A-Za-z\-]{10,}|ghp_[0-9A-Za-z]{30,}|sk_live_[0-9A-Za-z]{20,}|rk_live_[0-9A-Za-z]{20,})",
 "jwt-looking token": r"eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}",
 "postgres/redis url with password": r"(?:postgres(?:ql)?|redis|amqp)(?:\+\w+)?://[^\s'\"/:@]+:[^\s'\"@]+@",
 "env-var NAMES that should be server-only": r"\b(?:OPENAI_API_KEY|OPENAI_COMPAT_API_KEY|OPENROUTER_API_KEY|GEMINI_API_KEY|GOOGLE_CLIENT_SECRET|DATABASE_URL|REDIS_URL|JWT_SECRET|SECRET_KEY|STRIPE_SECRET_KEY|WEBHOOK_SECRET|SMTP_PASSWORD|AWS_SECRET_ACCESS_KEY|TOKEN_ENCRYPTION_KEY|AGENCY_TOKEN_ENCRYPTION_KEY|CASHFREE_SECRET\w*|RAZORPAY_KEY_SECRET|POSTGRES_PASSWORD|SENTRY_DSN)\b",
 "NEXT_PUBLIC_ variable names": r"NEXT_PUBLIC_[A-Z0-9_]+",
}
files = sys.argv[1:]
tot = 0
hits = {k: {} for k in pats}
for f in files:
    s = open(f, encoding="utf-8", errors="ignore").read()
    tot += len(s)
    for k, p in pats.items():
        for m in re.findall(p, s):
            hits[k][m[:60]] = hits[k].get(m[:60], 0) + 1
print(f"scanned {len(files)} files, {tot/1024:.0f} KB of JS/HTML")
for k, v in hits.items():
    if k.startswith("NEXT_PUBLIC"):
        print(f"- {k}: {sorted(v)}")
    elif v:
        shown = [x if "env-var" in k else (x[:6] + "…[redacted]") for x in v]
        print(f"- FOUND {k}: {len(v)} distinct -> {shown[:6]}")
    else:
        print(f"- clean: {k}")
