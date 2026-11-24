import test from "node:test";
import assert from "node:assert/strict";
import { ADMIN_BOTTOM, ADMIN_GROUPS, ADMIN_ITEMS, adminActive, adminHere } from "../src/lib/admin-nav.ts";

test("every operator page appears exactly once in the grouped navigation", () => {
  const hrefs = ADMIN_ITEMS.map((i) => i.href);
  assert.equal(new Set(hrefs).size, hrefs.length);
  for (const h of ["/admin", "/admin/customers", "/admin/users", "/admin/billing", "/admin/finance", "/admin/plans", "/admin/ops", "/admin/audit", "/admin/queue", "/admin/cards", "/admin/agency", "/admin/managed-usage",
    "/admin/whatsapp-prices", "/admin/whatsapp-ai", "/admin/whatsapp-entry-window", "/admin/whatsapp-festivals"]) assert.ok(hrefs.includes(h), h);
  assert.deepEqual(ADMIN_GROUPS.map((g) => g.id), ["command", "clients", "money", "plans", "ops", "admin"]);
});

test("a detail page keeps its list highlighted and Overview is only active on its own path", () => {
  assert.equal(adminHere("/admin/customers/abc-123/website")?.item.href, "/admin/customers");
  assert.equal(adminHere("/admin")?.item.href, "/admin");
  assert.equal(adminActive("/admin/customers", "/admin"), false);
  assert.equal(adminActive("/admin/customersx", "/admin/customers"), false);
  assert.equal(adminHere("/overview"), null);
});

test("the phone bottom bar holds four real pages", () => {
  assert.equal(ADMIN_BOTTOM.length, 4);
  for (const h of ADMIN_BOTTOM) assert.ok(ADMIN_ITEMS.some((i) => i.href === h), h);
});
