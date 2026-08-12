"""Parse and aggregate the USDA Pesticide Data Program (PDP) annual database.

PDP is the only large empirical residue dataset in this codebase. Unlike
`label_table.py` — where a human transcribes a primary document because no machine-
readable source exists — PDP publishes machine-readable files, so the honest thing is to
read them exactly as published and keep the provenance attached.

    https://www.ams.usda.gov/datasets/pdp/pdpdata

What one annual release contains (verified against the 2016 and 2024 releases):

    PDP<yy>Samples.txt   pipe-delimited, no header, one row per SAMPLE
    PDP<yy>Results.txt   pipe-delimited, no header, one row per (sample, compound) ASSAY
    PDP ReferenceTables <year>.xls[x]   commodity / pesticide / EPA tolerance lookups

The column orders below are transcribed from `PDP DataDictionary <year>.pdf` shipped
inside the same zip, and are asserted rather than assumed — see `_field`.

WHAT THIS MODULE IS CAREFUL ABOUT
---------------------------------

**A non-detect is a row, not a missing row.** Every compound in a sample's analytical
panel produces a Results row; a non-detect has an EMPTY `CONCEN`. So the denominator for
a detection rate is "rows for this pair", never "rows we happened to find a number in".
Counting only the numeric rows would report 100% detection for every compound ever found,
which is the single most misleading number this dataset can produce.

**A pair that was never analysed is absent, not zero.** If PDP did not run captan on
strawberries in a given year, the aggregate for that pair does not exist. `0 detections
out of 0 tested` is not a finding, and `0%` would read as "captan is never found on
strawberries" — the exact inversion this codebase refuses everywhere else (ENGINEERING_GUIDELINES.md §9).
`aggregate()` therefore emits nothing for an unanalysed pair, and the lookup layer
refuses rather than defaulting.

**Concentration units are per-row and are not normalised here.** PDP states M=ppm,
B=ppb, T=ppt. Mixing them silently would be a fabricated conversion; a pair whose rows
disagree on unit is reported with `unit_conflict=True` and no summary statistics, because
a max across two units is not a max. In practice a pair is single-unit.

Framework-free (stdlib only), no DB and no network, so it unit-tests in isolation —
ENGINEERING_GUIDELINES.md §6 layering rule.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from statistics import median
from typing import Iterable, Iterator

# --------------------------------------------------------------------------- layout
# Zero-based field positions, transcribed from `PDP DataDictionary <year>.pdf`.
# The dictionary has been stable across the 2016..2024 releases inspected; a release that
# changes it will trip the width assertion below rather than silently misread a column.

# Pdp<yy>Samples.txt — 18 fields
S_SAMPLE_PK = 0
S_STATE = 1
S_YEAR = 2
S_COMMOD = 6
S_ORIGIN = 9
S_COUNTRY = 10
S_COMMTYPE = 12
S_GROWST = 15
SAMPLES_FIELD_COUNT = 18

# Pdp<yy>Results.txt — 16 fields
R_SAMPLE_PK = 0
R_COMMOD = 1
R_COMMTYPE = 2
R_PESTCODE = 4
R_CONCEN = 6
R_LOD = 7
R_CONUNIT = 8
RESULTS_FIELD_COUNT = 16

# PDP origin codes (Samples.ORIGIN). "1" is domestic; the wedge cares about US-grown.
ORIGIN_DOMESTIC = "1"

# PDP concentration unit codes (Results.CONUNIT).
UNIT_CODES = {"M": "ppm", "B": "ppb", "T": "ppt"}


class PdpFormatError(ValueError):
    """A PDP file did not match the documented layout.

    Raised rather than skipped: a release whose columns moved would otherwise be read
    into the wrong fields and produce confident, wrong residue numbers.
    """


@dataclass(frozen=True)
class SampleRow:
    """One PDP sample — a physical unit of produce that was collected and analysed."""

    sample_pk: str
    commodity_code: str
    commodity_type: str
    origin: str
    country: str
    grower_state: str
    collected_state: str

    @property
    def is_domestic(self) -> bool:
        return self.origin == ORIGIN_DOMESTIC


@dataclass(frozen=True)
class ResidueAggregate:
    """One (commodity, pesticide, program year) pair, summarised over samples.

    Deliberately has NO field for a verdict, a risk band, a score, or an action. This is
    the `disease_risk.RiskAssessment` technique (ENGINEERING_GUIDELINES.md §4): the safest guarantee that
    residue statistics never become "do not spray this" is that there is nowhere to put
    such a conclusion. Callers get counts and concentrations and must reason in the open.

    `samples_tested` is the denominator — assays run, including non-detects.
    """

    commodity_code: str
    commodity_type: str
    pesticide_code: str
    program_year: int
    samples_tested: int
    samples_with_detection: int
    # None when nothing was detected: there is no maximum of an empty set, and 0.0 would
    # read as "detected at zero" rather than "never detected".
    max_concentration: float | None
    median_detected_concentration: float | None
    concentration_unit: str | None
    unit_conflict: bool
    domestic_only: bool

    @property
    def detection_rate(self) -> float | None:
        """Detections / assays. None when nothing was assayed — never 0.0."""
        if self.samples_tested <= 0:
            return None
        return self.samples_with_detection / self.samples_tested


def _split(line: str) -> list[str]:
    return line.rstrip("\r\n").split("|")


def _field(parts: list[str], index: int, expected_count: int, what: str) -> str:
    if len(parts) != expected_count:
        raise PdpFormatError(
            f"{what}: expected {expected_count} pipe-delimited fields per the PDP data "
            f"dictionary, found {len(parts)}. Refusing to read this release rather than "
            f"map columns by guesswork."
        )
    return parts[index].strip()


def parse_samples(lines: Iterable[str]) -> dict[str, SampleRow]:
    """Read Pdp<yy>Samples.txt into {sample_pk: SampleRow}. Blank lines ignored."""
    out: dict[str, SampleRow] = {}
    for raw in lines:
        if not raw.strip():
            continue
        parts = _split(raw)
        pk = _field(parts, S_SAMPLE_PK, SAMPLES_FIELD_COUNT, "Samples.txt")
        out[pk] = SampleRow(
            sample_pk=pk,
            commodity_code=parts[S_COMMOD].strip(),
            commodity_type=parts[S_COMMTYPE].strip(),
            origin=parts[S_ORIGIN].strip(),
            country=parts[S_COUNTRY].strip(),
            grower_state=parts[S_GROWST].strip(),
            collected_state=parts[S_STATE].strip(),
        )
    return out


def iter_results(lines: Iterable[str]) -> Iterator[tuple[str, str, str, str, float | None, str]]:
    """Stream Results.txt as (sample_pk, commodity, commtype, pestcode, concen, unit).

    A generator because the 2024 Results file is ~130 MB / 2.87 M rows; materialising it
    would make the loader's memory profile depend on USDA's sampling volume.

    `concen` is None for a non-detect (empty field), which is the documented encoding —
    NOT a parse failure and NOT a zero.
    """
    for raw in lines:
        if not raw.strip():
            continue
        parts = _split(raw)
        pk = _field(parts, R_SAMPLE_PK, RESULTS_FIELD_COUNT, "Results.txt")
        concen_raw = parts[R_CONCEN].strip()
        concen: float | None
        if concen_raw == "":
            concen = None
        else:
            try:
                concen = float(concen_raw)
            except ValueError as exc:
                raise PdpFormatError(
                    f"Results.txt sample {pk}: CONCEN {concen_raw!r} is neither a number "
                    "nor the documented empty non-detect."
                ) from exc
        yield (
            pk,
            parts[R_COMMOD].strip(),
            parts[R_COMMTYPE].strip(),
            parts[R_PESTCODE].strip(),
            concen,
            parts[R_CONUNIT].strip(),
        )


def aggregate(
    samples: dict[str, SampleRow],
    results: Iterable[tuple[str, str, str, str, float | None, str]],
    *,
    program_year: int,
    commodity_codes: set[str] | None = None,
    domestic_only: bool = False,
) -> list[ResidueAggregate]:
    """Summarise assays into per-(commodity, pesticide) aggregates.

    `commodity_codes` limits the work to the crops this product actually covers; None
    means every commodity in the release. `domestic_only` restricts to ORIGIN=1 samples,
    which is what a California grower's question is about — an imported sample's residue
    reflects another country's practice and another regulator's rules.

    A result row whose sample_pk is absent from `samples` is skipped: without the sample
    we cannot know its origin, and silently treating unknown origin as domestic would
    overstate the domestic denominator.
    """
    buckets: dict[tuple[str, str, str], dict] = {}

    for pk, commod, commtype, pestcode, concen, unit in results:
        sample = samples.get(pk)
        if sample is None:
            continue
        if domestic_only and not sample.is_domestic:
            continue
        if commodity_codes is not None and commod not in commodity_codes:
            continue
        if not pestcode:
            continue

        key = (commod, commtype, pestcode)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"tested": 0, "detected": [], "units": set()}
            buckets[key] = bucket

        bucket["tested"] += 1
        if concen is not None:
            bucket["detected"].append(concen)
            if unit:
                bucket["units"].add(unit)

    out: list[ResidueAggregate] = []
    for (commod, commtype, pestcode), bucket in sorted(buckets.items()):
        detected: list[float] = bucket["detected"]
        units: set[str] = bucket["units"]
        conflict = len(units) > 1
        unit_code = next(iter(units)) if len(units) == 1 else None
        out.append(
            ResidueAggregate(
                commodity_code=commod,
                commodity_type=commtype,
                pesticide_code=pestcode,
                program_year=program_year,
                samples_tested=bucket["tested"],
                samples_with_detection=len(detected),
                # Suppressed on a unit conflict: a maximum across ppm and ppb is not a
                # maximum of anything.
                max_concentration=(max(detected) if detected and not conflict else None),
                median_detected_concentration=(
                    median(detected) if detected and not conflict else None
                ),
                concentration_unit=UNIT_CODES.get(unit_code or "", None),
                unit_conflict=conflict,
                domestic_only=domestic_only,
            )
        )
    return out


def source_digest(*payloads: bytes) -> str:
    """Content digest of the raw release files, for provenance.

    Same instinct as `risk_snapshot`'s content addressing: a stored residue figure should
    be traceable to the exact bytes it was computed from, so a re-released or corrected
    PDP year is visibly a different source rather than a silent change in the numbers.
    """
    h = hashlib.sha256()
    for payload in payloads:
        h.update(hashlib.sha256(payload).digest())
    return h.hexdigest()
