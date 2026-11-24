import re, subprocess, sys, collections
pats = {
 "openai key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{30,}"),
 "openrouter key": re.compile(r"sk-or-v1-[A-Za-z0-9]{20,}"),
 "google api key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
 "google client secret": re.compile(r"GOCSPX-[0-9A-Za-z_\-]{20,}"),
 "aws key": re.compile(r"AKIA[0-9A-Z]{16}"),
 "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
 "github/slack/stripe token": re.compile(r"(?:ghp_[0-9A-Za-z]{30,}|xox[baprs]-[0-9A-Za-z\-]{10,}|sk_live_[0-9A-Za-z]{20,})"),
 "fernet-style 44-char key assigned": re.compile(r"(?:TOKEN_ENCRYPTION_KEY|AGENCY_TOKEN_ENCRYPTION_KEY|SECRET_KEY|JWT_SECRET)\s*[=:]\s*['\"]?([A-Za-z0-9_\-=]{43,44})['\"]?"),
 "password in url": re.compile(r"(?:postgres(?:ql)?|redis)(?:\+\w+)?://[^\s'\"/:@$]+:([^\s'\"@${}]{6,})@"),
 "cashfree/razorpay secret assigned": re.compile(r"(?:CASHFREE_(?:SECRET|APP_SECRET|CLIENT_SECRET)|RAZORPAY_KEY_SECRET|WEBHOOK_SECRET)\s*[=:]\s*['\"]?([A-Za-z0-9_\-]{16,})"),
}
# known harmless dev/test values to skip
SAFE = ("flowqr_dev", "flowqr_app_dev", "change-me", "changeme", "test", "example", "dummy", "x" * 6, "your", "<", "REPLACE", "Zm9yLXRlc3Rz")
p = subprocess.Popen(["git", "log", "--all", "-p", "--no-color", "--diff-filter=AM", "-U0", "--format=@@COMMIT %h"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore")
commit = file = ""
found = collections.OrderedDict()
n = 0
for line in p.stdout:
    if line.startswith("@@COMMIT "):
        commit = line.split()[1]; continue
    if line.startswith("+++ "):
        file = line[6:].strip(); continue
    if not line.startswith("+") or line.startswith("+++"):
        continue
    n += 1
    for name, rx in pats.items():
        m = rx.search(line)
        if m:
            val = m.group(1) if m.groups() else m.group(0)
            if any(s.lower() in (val + line).lower() for s in SAFE):
                continue
            key = (name, file)
            found.setdefault(key, set()).add(commit)
print(f"scanned {n:,} added lines across all branches")
if not found:
    print("no secret-shaped values found in history")
for (name, file), commits in found.items():
    print(f"- {name}: {file}  (in {len(commits)} commit(s), first {sorted(commits)[0]})  [value not printed]")
