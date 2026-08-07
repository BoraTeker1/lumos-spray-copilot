"""The shared spine for every EMPTY transcription source in this codebase.

`label_table.py` and `botrytis_thresholds.py` established the pattern independently:
a module that holds regulated or consequential numbers ships with its table EMPTY, and
those numbers arrive only by a human transcribing them from a primary document, with a
citation, one row at a time. `label_table.py` shipped empty for a month; the Botrytis
table is still `None` today, which is why the disease rule abstains on every input.

This module generalises the pattern so the finance, pricing and agronomic layers cannot
quietly do the easier thing. The easier thing — inventing a plausible coefficient — is
uniquely dangerous here, because a plausible number passes every test anyone would think
to write. There is no unit test that catches a made-up nitrogen removal rate, and there
is certainly none that catches a made-up credit weight; the only defence is that the
number cannot enter the system without a citation attached.

Three rules, all enforced at import time by the dataclasses below rather than by review:

1. **A value arrives with its citation or it does not arrive.** `Citation` is frozen and
   kw-only with NO defaults, so a row missing its document, section, or verbatim snippet
   raises when the module is imported — not when someone eventually reads the output.
2. **Empty means the source is silent, never "no limit" and never zero.** A model reading
   an empty table must return a `Refusal` naming the reason. `None` and `()` are the
   honest states, and every consumer in this codebase treats them that way.
3. **Every source names the document that would fill it.** `PRIMARY_SOURCE` is what makes
   the emptiness actionable rather than merely honest — it is the difference between "we
   don't know" and "here is exactly what someone must read." `TRANSCRIPTION_TASKS.md` is
   generated from these declarations, so the handoff doc cannot drift from the code.

Framework-free (stdlib only), like every other pure module here.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date

# What a source module must expose to be a transcription source at all.
ATTR_PRIMARY_SOURCE = "PRIMARY_SOURCE"
ATTR_TRANSCRIBED = "TRANSCRIBED"


@dataclass(frozen=True, kw_only=True)
class Citation:
    """Where a transcribed value came from, precisely enough to check it.

    Frozen and kw-only with no defaults on purpose: every field here is one someone
    would be tempted to skip, and each omission is the one that makes a number
    unverifiable later. `snippet` in particular must be VERBATIM — a paraphrase is a
    second transcription step with no record of the first.
    """

    document: str
    publisher: str
    section: str
    snippet: str
    transcribed_by: str
    transcribed_on: date
    revision: str | None = None
    effective_date: date | None = None

    def __post_init__(self) -> None:
        # A blank required field is the same failure as a missing one, and easier to
        # ship by accident: `section=""` type-checks and reads as filled-in at a glance.
        for name in ("document", "publisher", "section", "snippet", "transcribed_by"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(
                    f"Citation.{name} is blank. A transcribed value without a checkable "
                    "citation is indistinguishable from an invented one, which is the "
                    "entire failure mode this class exists to prevent."
                )


@dataclass(frozen=True)
class SourceStatus:
    """Whether one transcription source has been filled, and what would fill it."""

    module: str
    title: str
    primary_source: str
    populated: bool
    row_count: int

    def as_payload(self) -> dict:
        return {
            "module": self.module,
            "title": self.title,
            "primary_source": self.primary_source,
            "populated": self.populated,
            "row_count": self.row_count,
        }


class TranscriptionError(RuntimeError):
    """A module claimed to be a transcription source but does not meet the contract."""


def _row_count(transcribed: object) -> int:
    """How many transcribed entries a source holds.

    Sources come in two shapes and both are legitimate: a *sequence* of rows (a label
    library, a variety table) or a *single table object or None* (the Botrytis threshold
    grid, a lender's scorecard — one coherent artifact that is transcribed whole or not
    at all). Counting handles both rather than forcing one shape on every domain.
    """
    if transcribed is None:
        return 0
    if isinstance(transcribed, (tuple, list, frozenset, set)):
        return len(transcribed)
    if isinstance(transcribed, dict):
        return len(transcribed)
    return 1  # a single populated table object


def status_of(module_path: str, *, title: str = "") -> SourceStatus:
    """Import a transcription source and report whether anyone has filled it.

    Raises rather than returning a degraded status if the module does not meet the
    contract: a source that forgot to declare `PRIMARY_SOURCE` would otherwise show up
    in the handoff doc as an unfillable blank, which is worse than a loud failure.
    """
    module = importlib.import_module(module_path)

    primary_source = getattr(module, ATTR_PRIMARY_SOURCE, None)
    if not isinstance(primary_source, str) or not primary_source.strip():
        raise TranscriptionError(
            f"{module_path} must declare {ATTR_PRIMARY_SOURCE}: the document someone "
            "must read to fill it. Without that, its emptiness is not actionable."
        )
    if not hasattr(module, ATTR_TRANSCRIBED):
        raise TranscriptionError(
            f"{module_path} must declare {ATTR_TRANSCRIBED} (None or an empty sequence "
            "until transcribed)."
        )

    count = _row_count(getattr(module, ATTR_TRANSCRIBED))
    return SourceStatus(
        module=module_path,
        title=title or module_path.rsplit(".", 1)[-1],
        primary_source=primary_source.strip(),
        populated=count > 0,
        row_count=count,
    )
