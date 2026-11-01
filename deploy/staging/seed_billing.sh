#!/usr/bin/env bash
# Links the seeded staging tenant to a fake Razorpay subscription/plan/order in the DB so webhook scenarios can run.
# TEST DATA ONLY. Usage: deploy/staging/seed_billing.sh <tenant_id>
set -euo pipefail
T=${1:?tenant id}
COMPOSE=${COMPOSE:-docker compose}
$COMPOSE exec -T db psql -U flowqr -d flowqr -v ON_ERROR_STOP=1 -v t="$T" <<'SQL'
SELECT set_config('app.bypass_rls','on',false);
-- idempotent re-runs: move any previous staging link/order aside (renamed, not deleted)
UPDATE subscriptions SET razorpay_subscription_id = NULL WHERE razorpay_subscription_id='sub_STAGING0001' AND tenant_id <> :'t'::uuid;
UPDATE card_orders SET razorpay_order_id = 'order_STAGING_old_' || substr(id::text,1,8) WHERE razorpay_order_id='order_STAGING0001' AND tenant_id <> :'t'::uuid;
UPDATE billing_plans SET razorpay_plan_id='plan_STAGING_growth' WHERE code='growth';
UPDATE subscriptions SET razorpay_subscription_id='sub_STAGING0001' WHERE tenant_id = :'t';
INSERT INTO card_orders (id, tenant_id, quantity, unit_price_paise, amount_paise, currency, status, razorpay_order_id, shipping, created_at, updated_at)
VALUES (gen_random_uuid(), :'t', 10, 19900, 199000, 'INR', 'created', 'order_STAGING0001', '{"name":"Staging","city":"Lucknow"}', now(), now())
ON CONFLICT (razorpay_order_id) DO NOTHING;
SQL
