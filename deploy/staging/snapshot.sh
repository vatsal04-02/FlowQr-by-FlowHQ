#!/usr/bin/env bash
# Prints row counts + content checksums of the important tables (RLS bypassed as table owner). Used to prove backup/restore & persistence.
COMPOSE=${COMPOSE:-docker compose}
$COMPOSE exec -T db psql -U flowqr -d flowqr -At -F' ' <<'SQL'
SELECT set_config('app.bypass_rls','on',false) \gset
SELECT 'users', count(*), md5(string_agg(id::text||email||password_hash, ',' ORDER BY id)) FROM users
UNION ALL SELECT 'tenants', count(*), md5(string_agg(id::text||name, ',' ORDER BY id)) FROM tenants
UNION ALL SELECT 'memberships', count(*), md5(string_agg(id::text||role::text, ',' ORDER BY id)) FROM memberships
UNION ALL SELECT 'locations', count(*), md5(string_agg(id::text||name||coalesce(review_url,''), ',' ORDER BY id)) FROM locations
UNION ALL SELECT 'qr_cards', count(*), md5(string_agg(card_code||public_token||status::text, ',' ORDER BY card_code)) FROM qr_cards
UNION ALL SELECT 'card_batches', count(*), md5(string_agg(id::text||coalesce(base_url,''), ',' ORDER BY id)) FROM card_batches
UNION ALL SELECT 'scan_events', count(*), md5(string_agg(id::text||event_type::text, ',' ORDER BY id)) FROM scan_events
UNION ALL SELECT 'audit_logs', count(*), md5(string_agg(id::text||action, ',' ORDER BY id)) FROM audit_logs
UNION ALL SELECT 'subscriptions', count(*), md5(string_agg(id::text||status||plan, ',' ORDER BY id)) FROM subscriptions
UNION ALL SELECT 'payments', count(*), md5(string_agg(id::text||coalesce(razorpay_payment_id,'')||amount_paise::text, ',' ORDER BY id)) FROM payments
UNION ALL SELECT 'card_orders', count(*), md5(string_agg(id::text||status, ',' ORDER BY id)) FROM card_orders
UNION ALL SELECT 'webhook_events', count(*), md5(string_agg(event_id, ',' ORDER BY event_id)) FROM webhook_events
UNION ALL SELECT 'invitations', count(*), md5(string_agg(id::text||email, ',' ORDER BY id)) FROM invitations
UNION ALL SELECT 'card_code_seq', last_value, is_called::text FROM card_code_seq;
SQL
