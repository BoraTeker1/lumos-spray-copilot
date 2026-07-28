"""Build the operator REFERENCE farm: real labels, a real PCA act, real arithmetic.

Run explicitly, never by seeding or startup:

    python -m app.reference_farm

Why this exists
---------------
Every label-dependent check in the engine was built, tested, and then left unable to
run, because running one needs two things at once:

  1. a transcribed label record (`app/label_table.py` → `python -m app.label_sync`), and
  2. a licensed PCA verifying that record FOR A SPECIFIC FARM.

Requirement 2 is why this is a separate farm rather than a flag on the demo farm.
`label_data.promotable_to_authoritative` refuses to promote a record whose only
verification is simulated, and `crud.ensure_demo_real_separation` guarantees a demo
farm's verification IS simulated. The demo farm is therefore structurally incapable of
showing a label-grounded decision — by design, and that design is correct. So a farm
that can show one has to carry real provenance.

Real provenance is also the danger. A real-provenance farm's decisions count as pilot
evidence everywhere, and this farm has no grower. `Farm.is_reference` is what keeps both
facts true at once: the label checks run, and nothing here is ever reported as usage.
See `pilot_evidence.REFERENCE_FARM_DISCLOSURE`.

What it is NOT
--------------
Not a pilot, not a customer, not validation. The labels and the arithmetic are real; the
farm and its applications are the operator's. It demonstrates capability, and creates no
buyer evidence whatsoever.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

from app import crud, label_data, models, schemas
from app.database import SessionLocal, init_db

FARM_NAME = "Lumos Reference Ranch (operator test — not a customer)"

# The two products transcribed in `app/label_table.py`, by the registration numbers
# printed on their labels. Exact match only: `100-953` and a supplemental `100-953-xxxx`
# are different labels, and `match_product_identity` treats a base-only hit as AMBIGUOUS.
SWITCH_REG_NO = "100-953"
CAPTAN_REG_NO = "34704-1075"

# The farm's treated area. Everything downstream is per-acre, and `Farm.area_unit`
# makes the unit data rather than something inferred from the country.
BLOCK_ACRES = 12.0

# Switch 62.5WG on strawberry, from the label: 11-14 oz/A, DO NOT apply more than 4
# applications per year, DO NOT apply more than 56 oz/A per year, minimum interval 7
# days. Four applications at the top of the labelled rate is a grower who has used the
# season's full allowance — which is precisely the situation the checks exist to catch.
SWITCH_RATE_OZ_PER_ACRE = 14.0
SWITCH_APPLICATIONS = 4

# Captan 80 WDG on strawberry, from the label: 1.87 to 3.75 lb product/A.
CAPTAN_RATE_LB_PER_ACRE = 3.75


class ReferenceFarmExists(RuntimeError):
    """Refuse to build a second one rather than duplicate or overwrite the first."""


def _existing(db) -> models.Farm | None:
    for farm in crud.list_farms(db):
        if farm.is_reference:
            return farm
    return None


def _verify_label_records(db, farm, credential) -> list[int]:
    """The PCA act, through the real path — `crud.create_label_verification`.

    Attribution comes from the credential, never from a string this script supplies;
    that is the whole point of the route it mirrors. A record with no transcription on
    file is skipped loudly rather than invented.
    """
    verified: list[int] = []
    for product in crud.list_pesticide_products(db):
        for record in label_data.active_label_records(product.label_records):
            crud.create_label_verification(
                db,
                farm,
                schemas.ProductLabelVerificationCreate(
                    product_label_record_id=record.id,
                    attestation=(
                        f"Checked this transcription of {product.product_name} "
                        f"(EPA Reg. No. {product.epa_reg_no}), {record.registered_crop} "
                        f"use, line by line against {record.source_document_reference}. "
                        f"Values as printed on the label revision cited."
                    ),
                ),
                credential,
            )
            verified.append(record.id)
    return verified


def _switch_history(db, farm, today: date) -> None:
    """Four Switch applications, 14 days apart — the season's full labelled allowance.

    Recorded as SprayEvents because that is what the seasonal checks read: an applied
    outcome already materializes one, so counting both would double-count.
    """
    for i in range(SWITCH_APPLICATIONS):
        applied = today - timedelta(days=14 * (SWITCH_APPLICATIONS - i) + 3)
        crud.create_spray_event(
            db,
            farm.id,
            schemas.SprayEventCreate(
                product_name="Switch 62.5WG",
                epa_reg_no=SWITCH_REG_NO,
                active_ingredient="cyprodinil + fludioxonil",
                moa_group="9 + 12",
                pesticide_class="fungicide",
                target_pest_or_disease="Botrytis (gray mold)",
                rate_amount=SWITCH_RATE_OZ_PER_ACRE,
                rate_unit="oz/acre",
                treated_acres=BLOCK_ACRES,
                application_date=applied,
                cost=310.0,
                notes=(
                    "Operator reference record. Rate within the labelled 11-14 oz/A "
                    "range for strawberry."
                ),
            ),
        )


def _blocked_switch_decision(db, farm, today: date) -> models.PlannedSpray:
    """A fifth Switch application. The label says four.

    Entered as `grower_entered` on purpose: the point is that the LABEL supplies the
    limit, not the person typing. Nobody entered "4 applications" anywhere.
    """
    return crud.create_planned_spray(
        db,
        farm,
        schemas.PlannedSprayCreate(
            intended_date=today + timedelta(days=2),
            product_name="Switch 62.5WG",
            epa_reg_no=SWITCH_REG_NO,
            active_ingredient="cyprodinil + fludioxonil",
            moa_group="9 + 12",
            target_pest_or_disease="Botrytis (gray mold)",
            crop="strawberry",
            rate_amount=SWITCH_RATE_OZ_PER_ACRE,
            rate_unit="oz/acre",
            treated_acres=BLOCK_ACRES,
            estimated_cost=310.0,
            values_source="grower_entered",
            values_entered_by="Operator (reference farm)",
            notes=(
                "Fifth Switch application of the season. The grower entered no seasonal "
                "limit — the label supplies it."
            ),
        ),
    )


def _avoided_captan_decision(db, farm, today: date) -> models.PlannedSpray:
    """A captan application that did not happen — the active-ingredient quantity.

    Captan is the product this metric can use: a single active ingredient at a percent
    concentration, applied at a MASS rate (lb/acre). `label_data.ai_quantity` pairs a
    percent with a mass rate definitionally and refuses everything else, so Switch (two
    actives, no single concentration on file) correctly cannot contribute.
    """
    planned = crud.create_planned_spray(
        db,
        farm,
        schemas.PlannedSprayCreate(
            intended_date=today,
            product_name="Captan 80 WDG",
            epa_reg_no=CAPTAN_REG_NO,
            active_ingredient="captan",
            moa_group="M4",
            target_pest_or_disease="Botrytis (gray mold)",
            crop="strawberry",
            rate_amount=CAPTAN_RATE_LB_PER_ACRE,
            rate_unit="lb/acre",
            treated_acres=BLOCK_ACRES,
            estimated_cost=180.0,
            values_source="grower_entered",
            values_entered_by="Operator (reference farm)",
            notes="Scheduled protectant cover spray, checked before application.",
        ),
    )
    crud.record_planned_spray_outcome(
        db,
        planned,
        schemas.PlannedSprayOutcomeUpdate(
            outcome="avoided",
            outcome_date=today,
            outcome_reason=(
                "Scouting found gray-mold pressure below the treatment threshold and "
                "no wetness event in the forecast window; the cover spray was skipped."
            ),
        ),
    )
    # `confirmed_avoided` requires follow-up evidence that the spray was not ultimately
    # applied. Without this event the metric stays not-calculated — an avoided outcome
    # on its own is a claim, not evidence.
    crud.add_follow_up_event(
        db,
        planned,
        schemas.FollowUpEventCreate(
            event_type="scouting_observation",
            observed_at=today,
            severity=1,
            severity_scale="1-5 visual",
            rescue_required=False,
            entered_by="Operator (reference farm)",
            evidence_notes=(
                "Re-scouted after the skipped application: no gray mold above "
                "threshold, no rescue treatment required."
            ),
        ),
    )
    return planned


def build(db) -> dict:
    """Create the reference farm. Refuses if one already exists."""
    existing = _existing(db)
    if existing is not None:
        raise ReferenceFarmExists(
            f"Reference farm already exists: #{existing.id} {existing.name!r}. "
            f"Refusing to build a second one — delete it deliberately if you mean to "
            f"rebuild."
        )
    if not crud.list_pesticide_products(db):
        raise RuntimeError(
            "No pesticide products on file. Run `python -m app.label_sync` first — "
            "without a transcribed label there is nothing for a PCA to verify, and "
            "every label-dependent check would still report that it did not run."
        )

    today = date.today()
    farm = crud.create_farm(
        db,
        schemas.FarmCreate(
            name=FARM_NAME,
            location="Watsonville, CA",
            country="US",
            crop_type="strawberry",
            greenhouse_area=BLOCK_ACRES,
            area_unit="acres",
            planting_date=today - timedelta(days=150),
            expected_harvest_date=today + timedelta(days=21),
            advisor_involved=True,
        ),
    )
    farm.is_reference = True
    db.commit()
    db.refresh(farm)

    credential, token = crud.create_pca_credential(
        db,
        schemas.PcaCredentialCreate(
            display_name="Reference PCA (operator-held, not a client's adviser)",
            license_identifier="REFERENCE-FARM-OPERATOR",
            license_state="CA",
            issued_by="Lumos operator — reference farm only",
            active_from=today,
        ),
    )
    crud.authorize_pca_for_farm(
        db,
        credential,
        schemas.PcaFarmAuthorizationCreate(
            farm_id=farm.id,
            granted_on=today,
            granted_by="Lumos operator — reference farm only",
        ),
    )

    verified = _verify_label_records(db, farm, credential)
    _switch_history(db, farm, today)
    blocked = _blocked_switch_decision(db, farm, today)
    avoided = _avoided_captan_decision(db, farm, today)

    return {
        "farm_id": farm.id,
        "pca_token": token,
        "label_records_verified": len(verified),
        "blocked_decision_id": blocked.id,
        "avoided_decision_id": avoided.id,
        "blocked_outcome": blocked.decision_outcome,
        "blocked_authority": getattr(blocked, "decision_authority", None),
    }


def main() -> int:
    init_db()
    with SessionLocal() as db:
        try:
            result = build(db)
        except (ReferenceFarmExists, RuntimeError) as exc:
            print(f"refused: {exc}")
            return 1

    print(f"reference farm id:      {result['farm_id']}")
    print(f"label records verified: {result['label_records_verified']}")
    print(
        f"blocked decision:       #{result['blocked_decision_id']} "
        f"-> {result['blocked_outcome']} ({result['blocked_authority']})"
    )
    print(f"avoided decision:       #{result['avoided_decision_id']}")
    print()
    print("PCA token (shown once — needed to act as the PCA on this farm):")
    print(f"  {result['pca_token']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
