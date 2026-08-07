"""The marketplace layer: suppliers, catalogue, RFQ transmission, price dispersion.

Three things these tests exist to protect, in descending order of how much damage their
absence would do:

1. **The no-ranking commitment survives the catalogue.** Procurement was built with an
   explicit policy — quotes in entry order, no ranking column, no commission. Adding a
   product catalogue makes comparison possible for the first time, which is exactly when
   a "cheapest supplier" field becomes tempting. It must not appear.
2. **Dispersion groups by catalogue identity, never by name.** Free-text grouping reports
   three spellings of one product as three products with no spread each — which reads as
   "prices are consistent" when the truth is "we failed to group them".
3. **Transmission is inert and says so.** A submitted plan that silently contacts nobody
   is the gap this layer exists to make visible, not to paper over.
"""
import pytest

from app import procurement_analytics, rfq_transport
from app.refusal import CONVERSION_NOT_CITED, Refusal


class Line:
    """A quote line as `build_report` consumes it."""

    def __init__(self, product_id, name, supplier, price, unit="L", currency="USD",
                 quote_id=1):
        self.input_product_id = product_id
        self.product_name = name
        self.supplier_name = supplier
        self.unit_price = price
        self.unit = unit
        self.currency = currency
        self.quote_id = quote_id


# ------------------------------------------------------------- catalog_key
def test_catalog_key_absorbs_casing_and_spacing_only():
    """Exactly the differences that are certainly the same product, and nothing more."""
    assert procurement_analytics.catalog_key("Switch 62.5WG") == "switch 62.5wg"
    assert procurement_analytics.catalog_key("  SWITCH   62.5WG ") == "switch 62.5wg"
    assert procurement_analytics.catalog_key("Switch 62.5 WG") != "switch 62.5wg"


def test_catalog_key_is_none_for_nothing():
    assert procurement_analytics.catalog_key(None) is None
    assert procurement_analytics.catalog_key("   ") is None


# ------------------------------------------------------------- dispersion
def test_dispersion_reports_spread_across_suppliers():
    report = procurement_analytics.build_report([
        Line(1, "Switch 62.5WG", "Acme Ag", 100.0),
        Line(1, "Switch 62.5WG", "Valley Supply", 130.0),
    ])
    product = report.products[0]

    assert product.lowest == 100.0
    assert product.highest == 130.0
    assert product.spread == 30.0
    assert product.spread_pct == pytest.approx(30.0)


def test_a_single_quote_refuses_rather_than_reporting_zero_spread():
    """Zero spread reads as a competitive market rather than as an empty comparison."""
    report = procurement_analytics.build_report([
        Line(1, "Switch 62.5WG", "Acme Ag", 100.0),
    ])
    assert not report.products
    assert report.refusals[0].code == procurement_analytics.TOO_FEW_QUOTES


def test_mixed_units_refuse_rather_than_converting():
    report = procurement_analytics.build_report([
        Line(1, "Switch", "Acme Ag", 100.0, unit="L"),
        Line(1, "Switch", "Valley Supply", 100.0, unit="kg"),
    ])
    assert report.refusals[0].code == CONVERSION_NOT_CITED
    assert not report.products


def test_mixed_currencies_refuse():
    report = procurement_analytics.build_report([
        Line(1, "Switch", "Acme Ag", 100.0, currency="USD"),
        Line(1, "Switch", "Antalya Tarim", 100.0, currency="TRY"),
    ])
    assert report.refusals[0].code == CONVERSION_NOT_CITED


def test_unlinked_lines_are_counted_and_excluded_never_bucketed_by_name():
    """The reason the catalogue exists at all.

    Two spellings of one product, neither linked. Grouping by name would report two
    products with no spread each — 'prices are consistent' — when the truth is that the
    comparison never happened.
    """
    report = procurement_analytics.build_report([
        Line(None, "Switch 62.5WG", "Acme Ag", 100.0),
        Line(None, "Switch 62.5 WG", "Valley Supply", 130.0),
    ])
    assert report.products == ()
    assert report.refusals == ()
    assert report.unlinked_line_count == 2
    assert "grouping them by name" in report.as_payload()["unlinked_note"]


def test_dispersion_never_ranks_or_claims_a_saving():
    """The no-ranking commitment, at the point it becomes tempting to break."""
    payload = procurement_analytics.build_report([
        Line(1, "Switch", "Acme Ag", 130.0),
        Line(1, "Switch", "Valley Supply", 100.0),
    ]).as_payload()

    product = payload["products"][0]
    for forbidden in ("recommended", "best", "cheapest", "rank", "saving", "winner"):
        assert not any(forbidden in k.lower() for k in product), forbidden

    # Entry order preserved: the expensive supplier is still listed first.
    assert [o["supplier_name"] for o in product["observations"]] == [
        "Acme Ag", "Valley Supply"
    ]
    assert "recommended_supplier" in product["not_calculated"]
    assert "savings" in product["not_calculated"]


# ------------------------------------------------------------- transmission
def test_no_transport_configured_cannot_send():
    descriptor = rfq_transport.describe(env={})
    assert descriptor.can_send is False
    assert descriptor.transport == rfq_transport.TRANSPORT_NONE
    assert "LUMOS_RFQ_TRANSPORT" in descriptor.blocker


def test_email_transport_is_declared_but_still_inert():
    """Deliberate: a defect here emails real suppliers on a real grower's behalf."""
    descriptor = rfq_transport.describe(
        env={rfq_transport.ENV_TRANSPORT: "email"}
    )
    assert descriptor.transport == rfq_transport.TRANSPORT_EMAIL
    assert descriptor.can_send is False


def test_an_unrecognised_transport_falls_back_to_none_rather_than_sending():
    descriptor = rfq_transport.describe(
        env={rfq_transport.ENV_TRANSPORT: "carrier-pigeon"}
    )
    assert descriptor.can_send is False
    assert descriptor.transport == rfq_transport.TRANSPORT_NONE


def test_transmission_records_one_row_per_recipient_even_when_nothing_is_sent():
    """An empty list would read as 'nobody needed contacting'."""
    class S:
        def __init__(self, name):
            self.name = name
            self.contact_email = f"{name}@example.com"

    results = rfq_transport.transmit(
        suppliers=[S("acme"), S("valley")], plan_reference="input-plan-1", env={}
    )
    assert len(results) == 2
    assert {r.status for r in results} == {rfq_transport.STATUS_SKIPPED_NO_TRANSPORT}
    assert all(r.detail for r in results)


def test_a_transport_that_cannot_send_must_state_a_blocker():
    with pytest.raises(ValueError, match="must state a blocker"):
        rfq_transport.TransportDescriptor(
            transport=rfq_transport.TRANSPORT_NONE, can_send=False
        )


# ------------------------------------------------------------------- routes
def test_supplier_and_catalog_registration_round_trips(client):
    supplier = client.post("/internal/suppliers", json={
        "name": "Acme Ag Supply", "contact_email": "sales@acme.example",
    }).json()
    assert supplier["canonical_name"] == "acme ag supply"

    product = client.post("/internal/input-products", json={
        "category": "crop_protection", "name": "Switch 62.5WG",
    }).json()

    linked = client.post(f"/internal/suppliers/{supplier['id']}/catalog", json={
        "input_product_id": product["id"], "supplier_sku": "SW-625",
    })
    assert linked.status_code == 201

    catalog = client.get(f"/internal/suppliers/{supplier['id']}/catalog").json()
    assert len(catalog) == 1 and catalog[0]["supplier_sku"] == "SW-625"


def test_a_catalog_entry_carries_no_price(client):
    """A price on a catalogue row is a list price nobody quoted that goes stale unseen."""
    supplier = client.post("/internal/suppliers", json={"name": "Acme"}).json()
    product = client.post("/internal/input-products", json={
        "category": "fertilizer", "name": "Urea 46-0-0",
    }).json()
    entry = client.post(f"/internal/suppliers/{supplier['id']}/catalog", json={
        "input_product_id": product["id"],
    }).json()

    for forbidden in ("price", "cost", "rate"):
        assert not any(forbidden in k.lower() for k in entry), forbidden


def test_a_price_on_a_catalog_entry_is_rejected(client):
    supplier = client.post("/internal/suppliers", json={"name": "Acme"}).json()
    product = client.post("/internal/input-products", json={
        "category": "fertilizer", "name": "Urea",
    }).json()
    res = client.post(f"/internal/suppliers/{supplier['id']}/catalog", json={
        "input_product_id": product["id"], "unit_price": 42.0,
    })
    # Pydantic ignores unknown fields by default; the assertion that matters is that it
    # never lands on the row.
    assert "unit_price" not in res.json()


def test_the_supplier_list_is_not_ranked(client):
    """Registration order. Sorting a supplier list is a recommendation."""
    for name in ("Zenith Ag", "Acme Ag", "Meridian Supply"):
        client.post("/internal/suppliers", json={"name": name})

    listed = [s["name"] for s in client.get("/internal/suppliers").json()]
    assert listed == ["Zenith Ag", "Acme Ag", "Meridian Supply"]


def test_inactive_suppliers_are_hidden_by_default_but_never_deleted(client):
    """A deleted supplier orphans a quote a grower already acted on."""
    client.post("/internal/suppliers", json={"name": "Gone Co", "status": "inactive"})

    assert client.get("/internal/suppliers").json() == []
    assert len(client.get("/internal/suppliers?include_inactive=true").json()) == 1


def test_rfq_transport_status_is_reported_not_hidden(client):
    body = client.get("/rfq-transport").json()
    assert body["can_send"] is False
    assert body["blocker"]


def test_transmitting_an_rfq_records_the_skip(client):
    supplier = client.post("/internal/suppliers", json={"name": "Acme"}).json()

    farm = client.post("/farms", json={
        "name": "Plan Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 10.0,
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "title": "Fungicide block", "needed_by": "2026-09-01",
    }).json()

    res = client.post(f"/input-plans/{plan['id']}/transmit-rfq", json={
        "supplier_ids": [supplier["id"]], "requested_by": "operator",
    })
    assert res.status_code == 201
    row = res.json()[0]
    assert row["status"] == "skipped_no_transport"
    assert row["detail"]

    history = client.get(f"/input-plans/{plan['id']}/transmissions").json()
    assert len(history) == 1


def test_transmissions_are_append_only(client):
    """Re-sending is a NEW row, never an edit of the old one."""
    supplier = client.post("/internal/suppliers", json={"name": "Acme"}).json()
    farm = client.post("/farms", json={
        "name": "Append Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 5.0,
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "title": "Plan", "needed_by": "2026-09-01",
    }).json()

    for _ in range(2):
        client.post(f"/input-plans/{plan['id']}/transmit-rfq",
                    json={"supplier_ids": [supplier["id"]]})

    assert len(client.get(f"/input-plans/{plan['id']}/transmissions").json()) == 2


def test_transmitting_to_unknown_suppliers_is_a_404(client):
    farm = client.post("/farms", json={
        "name": "X", "location": "Y", "country": "US", "crop_type": "strawberry",
        "area": 1.0,
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "title": "P", "needed_by": "2026-09-01",
    }).json()

    res = client.post(f"/input-plans/{plan['id']}/transmit-rfq",
                      json={"supplier_ids": [99999]})
    assert res.status_code == 404


def test_the_catalog_link_is_reachable_from_the_quote_entry_schema():
    """The delivery-gap check, and the reason it is worth its own test.

    ENGINEERING_GUIDELINES.md §5 records an audit that found `epa_reg_no` was not a field in
    `PreSpraySheet.js` at all, so five phases of label work were unreachable from the
    primary workflow. This layer has the identical failure mode: without
    `input_product_id` on the quote-item schema, no line can ever be catalogued,
    `build_report` reports 100% unlinked forever, and the catalogue is decorative.

    Asserting on the schema rather than on a docstring, because that is the thing that
    actually determines reachability.
    """
    from app import schemas

    assert "input_product_id" in schemas.SupplierQuoteItemCreate.model_fields
    assert "supplier_id" in schemas.SupplierQuoteCreate.model_fields
    # And it must survive to the read side, or the UI cannot show what it linked.
    assert "input_product_id" in schemas.SupplierQuoteItem.model_fields


def test_a_catalogued_quote_line_enters_the_dispersion_end_to_end(client):
    """The whole chain: catalogue -> quote -> dispersion, through the real API.

    Two suppliers quote the SAME catalogued product at different prices. If any link in
    the chain is unreachable, this reports an unlinked line instead of a spread.
    """
    farm = client.post("/farms", json={
        "name": "E2E Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 10.0,
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "title": "Fungicide", "needed_by": "2026-09-01",
    }).json()
    # NOTE the two `category` vocabularies are deliberately different and not a typo:
    # an InputPlanItem's category is its agronomic PURPOSE (fungicide/insecticide/…),
    # while an InputProduct's is its catalogue CLASS (crop_protection/fertilizer/seed/…).
    # A fungicide and an insecticide are both crop_protection products.
    item = client.post(f"/input-plans/{plan['id']}/items", json={
        "product_name": "Switch 62.5WG", "category": "fungicide",
        "quantity": 10.0, "unit": "L", "needed_by_date": "2026-09-01",
    }).json()
    client.post(f"/input-plans/{plan['id']}/submit", json={})

    product = client.post("/internal/input-products", json={
        "category": "crop_protection", "name": "Switch 62.5WG",
    }).json()

    for supplier_name, price in (("Acme Ag", 100.0), ("Valley Supply", 130.0)):
        res = client.post(f"/internal/input-plans/{plan['id']}/quotes", json={
            "supplier_name": supplier_name,
            "items": [{
                "input_plan_item_id": item["id"],
                "product_name": "Switch 62.5WG",
                "input_product_id": product["id"],
                "quantity": 10.0, "unit": "L", "unit_price": price,
            }],
        })
        assert res.status_code == 201, res.text

    body = client.get(f"/input-plans/{plan['id']}/price-dispersion").json()

    assert body["unlinked_line_count"] == 0, "the catalogue link did not survive the chain"
    assert len(body["products"]) == 1
    dispersion = body["products"][0]
    assert dispersion["quote_count"] == 2
    assert dispersion["lowest_unit_price"] == 100.0
    assert dispersion["highest_unit_price"] == 130.0
    assert dispersion["spread_pct"] == pytest.approx(30.0)


def test_price_dispersion_route_responds_for_a_plan_with_no_quotes(client):
    farm = client.post("/farms", json={
        "name": "Dispersion Ranch", "location": "Watsonville, CA", "country": "US",
        "crop_type": "strawberry", "area": 10.0,
    }).json()
    plan = client.post(f"/farms/{farm['id']}/input-plans", json={
        "title": "Plan", "needed_by": "2026-09-01",
    }).json()

    body = client.get(f"/input-plans/{plan['id']}/price-dispersion").json()
    assert body["products"] == []
    assert body["unlinked_line_count"] == 0
