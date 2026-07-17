"""Canonical status derivation for the Inputs & finance module (single source of truth).

Every "may this plan be submitted / is this quote still selectable / what does this
financing offer currently mean" question anywhere in the app (routes, crud gates,
evidence aggregation, API schema fields the frontend renders) MUST come from these
helpers — the same rule that app/decision_status.py enforces for decisions.

Phase 1 scope notes baked into the vocabulary:

* An input plan IS the RFQ — submitting it for quotes is a status transition, not a
  separate record.
* "Financing requested" is a flag on the plan, never an offer row — a request is
  structurally incapable of looking like an approval.
* Quotes and offers are never edited; the correction path is withdraw + re-enter,
  so what the grower saw is preserved without a parallel audit system.
* Expiry is always DERIVED from ``expires_on`` against an injected ``today`` —
  never stored — so a stale row can't claim to be live.

Framework-free: duck-typed plain objects only, no FastAPI/SQLAlchemy imports, and
no clock import — callers inject ``today`` (see app/clock.py contract).
"""
from __future__ import annotations

# --------------------------------------------------------------------- Input plan
PLAN_DRAFT = "draft"
PLAN_SUBMITTED = "submitted_for_quotes"
PLAN_QUOTED = "quoted"
PLAN_QUOTE_SELECTED = "quote_selected"
PLAN_ORDERED = "ordered"
PLAN_CANCELLED = "cancelled"

PLAN_STATUSES = (
    PLAN_DRAFT,
    PLAN_SUBMITTED,
    PLAN_QUOTED,
    PLAN_QUOTE_SELECTED,
    PLAN_ORDERED,
    PLAN_CANCELLED,
)

# Allowed forward transitions. Anything not listed is an invalid transition (409).
# There is deliberately no "closed": ordered/cancelled are the plan's terminal
# states — post-order progress lives in the order's event timeline, never here.
PLAN_TRANSITIONS = {
    PLAN_DRAFT: (PLAN_SUBMITTED, PLAN_CANCELLED),
    PLAN_SUBMITTED: (PLAN_QUOTED, PLAN_CANCELLED),
    PLAN_QUOTED: (PLAN_QUOTE_SELECTED, PLAN_CANCELLED),
    PLAN_QUOTE_SELECTED: (PLAN_ORDERED, PLAN_CANCELLED),
    PLAN_ORDERED: (),
    PLAN_CANCELLED: (),
}


def plan_transition_allowed(current: str, new: str) -> bool:
    """May a plan move from ``current`` to ``new``? (Cancel after ordered: no.)"""
    return new in PLAN_TRANSITIONS.get(current, ())


def plan_is_mutable(plan) -> bool:
    """Header and items may change only while the plan is a draft.

    After submission the RFQ is what suppliers were asked to quote — editing it
    would silently invalidate quotes already entered against it.
    """
    return getattr(plan, "status", None) == PLAN_DRAFT


# Statuses in which the concierge may still enter quotes.
PLAN_QUOTABLE_STATUSES = (PLAN_SUBMITTED, PLAN_QUOTED)


# ---------------------------------------------------------------- Financing state
# Derived per plan from its flag + every offer on its quotes. A request with zero
# offers is honestly "requested, awaiting terms" — never an offer, never an approval.
FINANCING_CASH = "cash"
FINANCING_REQUESTED = "financing_requested"
FINANCING_OFFER_RECEIVED = "offer_received"
FINANCING_OFFER_ACCEPTED = "offer_accepted"
FINANCING_OFFER_DEAD = "offer_declined_or_expired"

FINANCING_STATES = (
    FINANCING_CASH,
    FINANCING_REQUESTED,
    FINANCING_OFFER_RECEIVED,
    FINANCING_OFFER_ACCEPTED,
    FINANCING_OFFER_DEAD,
)


def financing_state(plan, offers, today) -> str:
    """The one financing situation of a plan, derived — never stored.

    cash — financing was never requested.
    financing_requested — requested; no indicative terms entered yet.
    offer_received — at least one live (unexpired, undecided) indicative offer.
    offer_accepted — the grower accepted indicative terms (still not a loan).
    offer_declined_or_expired — offers existed but none is live or accepted.
    """
    if not getattr(plan, "financing_requested", False):
        return FINANCING_CASH
    offers = list(offers or [])
    if any(getattr(o, "status", None) == OFFER_ACCEPTED for o in offers):
        return FINANCING_OFFER_ACCEPTED
    if any(offer_state(o, today) == OFFER_INDICATIVE for o in offers):
        return FINANCING_OFFER_RECEIVED
    if offers:
        return FINANCING_OFFER_DEAD
    return FINANCING_REQUESTED


# ------------------------------------------------------------------ Supplier quote
# Stored statuses (mutated only by the select/withdraw endpoints).
QUOTE_SUBMITTED = "submitted"
QUOTE_SELECTED = "selected"
QUOTE_WITHDRAWN = "withdrawn"

QUOTE_STATUSES = (QUOTE_SUBMITTED, QUOTE_SELECTED, QUOTE_WITHDRAWN)

# Derived states add the two situations that are never stored.
QUOTE_NOT_SELECTED = "not_selected"
QUOTE_EXPIRED = "expired"

QUOTE_STATES = (
    QUOTE_SUBMITTED,
    QUOTE_SELECTED,
    QUOTE_NOT_SELECTED,
    QUOTE_WITHDRAWN,
    QUOTE_EXPIRED,
)


def quote_state(quote, plan, today) -> str:
    """What this quote currently means to the grower.

    selected / withdrawn are stored facts; not_selected (a sibling won) and
    expired (expires_on has passed, and it was never selected) are derived.
    """
    status = getattr(quote, "status", None)
    if status in (QUOTE_SELECTED, QUOTE_WITHDRAWN):
        return status
    selected_id = getattr(plan, "selected_quote_id", None)
    if selected_id is not None and selected_id != getattr(quote, "id", None):
        return QUOTE_NOT_SELECTED
    expires_on = getattr(quote, "expires_on", None)
    if expires_on is not None and expires_on < today:
        return QUOTE_EXPIRED
    return QUOTE_SUBMITTED


def quote_selectable(quote, today) -> bool:
    """May the grower select this quote right now? (Expired/withdrawn: no.)"""
    if getattr(quote, "status", None) != QUOTE_SUBMITTED:
        return False
    expires_on = getattr(quote, "expires_on", None)
    return expires_on is None or expires_on >= today


# Shipped verbatim with every serialized offer and in the evidence export.
FINANCING_OFFER_DISCLAIMER = (
    "Indicative terms manually entered by the Lumos concierge. Not a credit "
    "decision, not a loan offer, not an approval. Any actual financing is between "
    "the grower and the provider."
)

# ---------------------------------------------------------------- Financing offer
# Stored statuses. "indicative" is the only state an offer is created in; a
# decision (accepted/declined) is one-shot; withdrawn is the concierge correction.
OFFER_INDICATIVE = "indicative"
OFFER_ACCEPTED = "accepted"
OFFER_DECLINED = "declined"
OFFER_WITHDRAWN = "withdrawn"

OFFER_STATUSES = (OFFER_INDICATIVE, OFFER_ACCEPTED, OFFER_DECLINED, OFFER_WITHDRAWN)

# Derived-only state.
OFFER_EXPIRED = "expired"

OFFER_STATES = OFFER_STATUSES + (OFFER_EXPIRED,)


def offer_state(offer, today) -> str:
    """The offer's current meaning; expiry is derived so it can never be accepted late."""
    status = getattr(offer, "status", None)
    if status != OFFER_INDICATIVE:
        return status
    expires_on = getattr(offer, "expires_on", None)
    if expires_on is not None and expires_on < today:
        return OFFER_EXPIRED
    return OFFER_INDICATIVE


def offer_decidable(offer, today) -> bool:
    """May the grower accept/decline this offer right now?"""
    return offer_state(offer, today) == OFFER_INDICATIVE


# ---------------------------------------------------------------- Purchase order
ORDER_PLACED = "placed"
ORDER_CONFIRMED = "confirmed"
ORDER_SHIPPED = "shipped"
ORDER_DELIVERED = "delivered"
ORDER_PARTIALLY_DELIVERED = "partially_delivered"
ORDER_CANCELLED = "cancelled"

ORDER_STATUSES = (
    ORDER_PLACED,
    ORDER_CONFIRMED,
    ORDER_SHIPPED,
    ORDER_DELIVERED,
    ORDER_PARTIALLY_DELIVERED,
    ORDER_CANCELLED,
)

# Order event types. The first three are written only by order creation and are
# never postable afterwards — they record how the order came to exist.
EVENT_CREATED = "created"
EVENT_QUOTE_SELECTED = "quote_selected"
EVENT_FINANCING_SELECTED = "financing_selected"
EVENT_SUPPLIER_CONFIRMED = "supplier_confirmed"
EVENT_SHIPPED = "shipped"
EVENT_DELIVERED = "delivered"
EVENT_PARTIALLY_DELIVERED = "partially_delivered"
EVENT_CANCELLED = "cancelled"
EVENT_INPUT_APPLIED = "input_applied"
EVENT_EXCEPTION_REPORTED = "exception_reported"

ORDER_EVENT_TYPES = (
    EVENT_CREATED,
    EVENT_QUOTE_SELECTED,
    EVENT_FINANCING_SELECTED,
    EVENT_SUPPLIER_CONFIRMED,
    EVENT_SHIPPED,
    EVENT_DELIVERED,
    EVENT_PARTIALLY_DELIVERED,
    EVENT_CANCELLED,
    EVENT_INPUT_APPLIED,
    EVENT_EXCEPTION_REPORTED,
)

# Which order statuses each postable event may be appended FROM. Posting an event
# whose prior status isn't listed is a 409 — this map is also the idempotency
# guard (a second "delivered" 409s because delivered isn't in its own from-list).
ORDER_EVENT_ALLOWED_FROM = {
    EVENT_SUPPLIER_CONFIRMED: (ORDER_PLACED,),
    EVENT_SHIPPED: (ORDER_PLACED, ORDER_CONFIRMED),
    EVENT_DELIVERED: (
        ORDER_PLACED, ORDER_CONFIRMED, ORDER_SHIPPED, ORDER_PARTIALLY_DELIVERED,
    ),
    EVENT_PARTIALLY_DELIVERED: (
        ORDER_PLACED, ORDER_CONFIRMED, ORDER_SHIPPED, ORDER_PARTIALLY_DELIVERED,
    ),
    EVENT_CANCELLED: (
        ORDER_PLACED, ORDER_CONFIRMED, ORDER_SHIPPED, ORDER_PARTIALLY_DELIVERED,
    ),
    # input_applied never changes status and is only meaningful once goods arrived.
    # Delivery alone NEVER marks an input as applied — this event requires an
    # explicit application link and has its own endpoint.
    EVENT_INPUT_APPLIED: (ORDER_DELIVERED, ORDER_PARTIALLY_DELIVERED),
    EVENT_EXCEPTION_REPORTED: (
        ORDER_PLACED, ORDER_CONFIRMED, ORDER_SHIPPED,
        ORDER_DELIVERED, ORDER_PARTIALLY_DELIVERED,
    ),
}

# The order status each event moves the order TO (absent = status unchanged).
ORDER_EVENT_NEW_STATUS = {
    EVENT_SUPPLIER_CONFIRMED: ORDER_CONFIRMED,
    EVENT_SHIPPED: ORDER_SHIPPED,
    EVENT_DELIVERED: ORDER_DELIVERED,
    EVENT_PARTIALLY_DELIVERED: ORDER_PARTIALLY_DELIVERED,
    EVENT_CANCELLED: ORDER_CANCELLED,
}

# Events the concierge may post via the generic /internal order-events endpoint.
# input_applied is excluded: it needs an explicit application link and goes
# through its own endpoint so delivery can never be conflated with application.
CONCIERGE_POSTABLE_EVENTS = (
    EVENT_SUPPLIER_CONFIRMED,
    EVENT_SHIPPED,
    EVENT_DELIVERED,
    EVENT_PARTIALLY_DELIVERED,
    EVENT_CANCELLED,
    EVENT_EXCEPTION_REPORTED,
)


def order_event_allowed(order, event_type) -> bool:
    """May ``event_type`` be appended given the order's current status?"""
    allowed_from = ORDER_EVENT_ALLOWED_FROM.get(event_type, ())
    return getattr(order, "status", None) in allowed_from
