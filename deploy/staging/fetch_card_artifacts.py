#!/usr/bin/env python3
"""Downloads a real card PNG/SVG + batch ZIP from the running stack into /out (decode them on the host with OpenCV)."""
import json, os, httpx
D = os.environ.get("STAGING_DOMAIN", "flowqr-staging.dev"); seed = json.load(open("/out/seed.json"))
c = httpx.Client(base_url=f"https://app.{D}/api/v1", timeout=30)
r = c.post("/auth/login", json={"email": seed["admin"]["email"], "password": seed["admin"]["password"]}); H = {"X-CSRF-Token": r.json()["csrf_token"]}
cards = c.get("/admin/cards", params={"search": seed["card"]["code"]}, headers=H).json()["items"]; card = cards[0]
open("/out/card.png", "wb").write(c.get(f"/admin/cards/{card['id']}/qr.png", headers=H).content)
open("/out/card.svg", "wb").write(c.get(f"/admin/cards/{card['id']}/qr.svg", headers=H).content)
b = c.get("/admin/batches", headers=H).json()[0]
open("/out/batch.zip", "wb").write(c.get(f"/admin/batches/{b['id']}/export.zip", headers=H).content)
open("/out/sheet.html", "wb").write(c.get(f"/admin/batches/{b['id']}/sheet", headers=H).content)
json.dump({"url": card["url"], "code": card["card_code"]}, open("/out/card.json", "w"))
