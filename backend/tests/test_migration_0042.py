"""Migration 0042 (card destinations, NFC status, richer scan events): additive, tenant-isolated, reversible, no existing card or event changed."""
from tests.conftest import make_business, owner_query
from tests.test_migration_0037 import alembic


def cols(table):
    return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=table)}


def test_new_columns_and_the_append_only_history_table_exist_with_the_right_protections():
    assert {"destination_url", "destination_set_at", "nfc_programmed_at", "nfc_programmed_by"} <= cols("qr_cards")
    assert {"referrer_host", "device", "placement", "campaign_id"} <= cols("scan_events")
    assert owner_query("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'card_destination_history'")[0] == (True, True)
    assert "ck_card_destination_action" in {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'card_destination_history'::regclass")}


def test_downgrade_keeps_every_card_and_event_and_upgrade_restores_the_pieces():
    biz = make_business()
    before = owner_query("SELECT (SELECT count(*) FROM qr_cards), (SELECT count(*) FROM scan_events), (SELECT md5(string_agg(public_token, ',' ORDER BY public_token)) FROM qr_cards)")[0]
    alembic("downgrade", "0041")
    try:
        assert not ({"destination_url", "nfc_programmed_at"} & cols("qr_cards")) and not ({"referrer_host", "device"} & cols("scan_events"))
        assert not owner_query("SELECT to_regclass('public.card_destination_history')")[0][0]
        assert owner_query("SELECT (SELECT count(*) FROM qr_cards), (SELECT count(*) FROM scan_events), (SELECT md5(string_agg(public_token, ',' ORDER BY public_token)) FROM qr_cards)")[0] == before
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0059" and "destination_url" in cols("qr_cards")
    assert owner_query("SELECT count(*) FROM qr_cards WHERE destination_url IS NOT NULL")[0][0] == 0  # nothing existing was given a destination
    assert biz.tenant_id
