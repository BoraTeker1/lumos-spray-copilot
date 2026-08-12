"""RFQ transmission (pure, framework-free).

Before this module, "submit for quotes" set a status column and stopped. The RFQ was
never transmitted to anybody; a Lumos operator was expected to notice it in a dropdown
on `/internal` and email the supplier themselves. That is a real gap between what the
procurement state machine claims and what happens, and it is invisible until a grower
asks why nobody quoted.

This closes the gap **honestly rather than by adding an email client**: transmission
becomes a real, recorded, auditable step whose current answer is "no transport is
configured, so nothing was sent" — recorded as such on an append-only row, rather than
silently not happening.

**The inertness contract is copied deliberately from `ingest/cimis.py`.** That adapter
asks `describe()` before `fetch()`, so a deployment with no credential is inert *by
construction* rather than by an operator remembering not to run it. The same shape here:
`describe()` reports whether a transport is configured, `transmit()` refuses when it is
not, and the caller checks `can_send` before doing anything. A deployment with no SMTP
configuration cannot accidentally email a real supplier.

**What this is not.** It is not a supplier portal, and it does not make Lumos a broker.
An RFQ goes to suppliers the grower or operator named, in entry order, with no ranking
and no commission — the procurement module's existing commitments are unchanged.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# Transport identities. `manual` is the honest description of what happens today when
# someone copies the RFQ into their own mail client — it is a real transport, it just
# is not automated, and recording it is better than pretending no transmission occurred.
TRANSPORT_NONE = "none"
TRANSPORT_MANUAL = "manual"
TRANSPORT_EMAIL = "email"

TRANSPORTS = (TRANSPORT_NONE, TRANSPORT_MANUAL, TRANSPORT_EMAIL)

# Outcomes recorded on an RfqTransmission row.
STATUS_QUEUED = "queued"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_SKIPPED_NO_TRANSPORT = "skipped_no_transport"

TRANSMISSION_STATUSES = (
    STATUS_QUEUED, STATUS_SENT, STATUS_FAILED, STATUS_SKIPPED_NO_TRANSPORT,
)

# The environment variable that would configure a real transport. Absent today on every
# deployment, which is why every transmission row says `skipped_no_transport`.
ENV_TRANSPORT = "LUMOS_RFQ_TRANSPORT"


@dataclass(frozen=True)
class TransportDescriptor:
    """What transport is configured and whether it can send right now.

    Mirrors `ingest.base.SourceDescriptor`: `blocker` is required whenever sending is
    impossible, because "not configured" with no next action tells an operator nothing
    they could not already see.
    """

    transport: str
    can_send: bool
    blocker: str | None = None

    def __post_init__(self) -> None:
        if self.transport not in TRANSPORTS:
            raise ValueError(
                f"unknown transport {self.transport!r}; declared transports are {TRANSPORTS}"
            )
        if not self.can_send and not self.blocker:
            raise ValueError(
                f"{self.transport}: a transport that cannot send must state a blocker"
            )

    def as_payload(self) -> dict:
        return {
            "transport": self.transport,
            "can_send": self.can_send,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class TransmissionResult:
    """The outcome of one attempted transmission, for one supplier."""

    supplier_name: str
    transport: str
    status: str
    detail: str
    sent_to: str | None = None

    def __post_init__(self) -> None:
        if self.status not in TRANSMISSION_STATUSES:
            raise ValueError(f"unknown transmission status {self.status!r}")


def describe(env: dict | None = None) -> TransportDescriptor:
    """What transport this deployment has, read fresh from the environment.

    Read at call time rather than import time, matching `registry._ADAPTER_FACTORIES`'s
    reasoning: an operator who exports a variable and restarts a worker must not have to
    reason about when this module was first imported.
    """
    environ = os.environ if env is None else env
    configured = (environ.get(ENV_TRANSPORT) or "").strip().lower()

    if not configured or configured == TRANSPORT_NONE:
        return TransportDescriptor(
            transport=TRANSPORT_NONE,
            can_send=False,
            blocker=(
                f"No RFQ transport is configured ({ENV_TRANSPORT} is unset). RFQs are "
                "recorded as skipped and must be sent by a human until one is. Nothing "
                "in this deployment can contact a supplier."
            ),
        )

    if configured == TRANSPORT_MANUAL:
        return TransportDescriptor(
            transport=TRANSPORT_MANUAL,
            can_send=False,
            blocker=(
                "Transport is set to `manual`: an operator sends the RFQ from their own "
                "mail client and the row records that it left the building. Lumos does "
                "not send it."
            ),
        )

    if configured == TRANSPORT_EMAIL:
        # Deliberately still inert. Wiring a real SMTP client is a decision with a blast
        # radius — a bug here emails real suppliers on behalf of a real grower — and it
        # should be made deliberately with credentials in hand, not inherited from a
        # build that had none to test against.
        return TransportDescriptor(
            transport=TRANSPORT_EMAIL,
            can_send=False,
            blocker=(
                "Email transport is declared but no client is implemented. This is "
                "deliberate: a defect here would email real suppliers on a real "
                "grower's behalf, so the client should be written against live "
                "credentials by someone who can test it end to end."
            ),
        )

    return TransportDescriptor(
        transport=TRANSPORT_NONE,
        can_send=False,
        blocker=f"Unrecognised {ENV_TRANSPORT} value {configured!r}; expected one of {TRANSPORTS}.",
    )


def transmit(*, suppliers, plan_reference: str, env: dict | None = None):
    """Attempt to transmit an RFQ to each supplier. Returns a TransmissionResult each.

    Always returns one result per supplier, including when nothing was sent — a plan
    submitted with no transport must leave a record saying so for each intended
    recipient, not an empty list that reads as "nobody needed contacting".
    """
    descriptor = describe(env)
    results = []

    for supplier in suppliers or ():
        name = getattr(supplier, "name", None) or str(supplier)
        address = getattr(supplier, "contact_email", None)

        if not descriptor.can_send:
            results.append(TransmissionResult(
                supplier_name=name,
                transport=descriptor.transport,
                status=STATUS_SKIPPED_NO_TRANSPORT,
                detail=descriptor.blocker,
                sent_to=address,
            ))
            continue

        # Unreachable today — `describe()` never returns can_send=True. Kept so the
        # contract is visible and the day someone implements a client, the shape of
        # what they must produce is already here.
        results.append(TransmissionResult(  # pragma: no cover
            supplier_name=name,
            transport=descriptor.transport,
            status=STATUS_QUEUED,
            detail=f"Queued for {descriptor.transport} transport: {plan_reference}",
            sent_to=address,
        ))

    return results
