"""Load transcribed label uses into the database.

    python -m app.label_sync

Deliberately an explicit command, not something `init_db()` or `seed.run()` does. Two
reasons, and they are different:

  * Seeding label data would make demo decisions look label-grounded, which is a
    fabricated regulatory claim — the one kind of "never present seed data as traction"
    (ENGINEERING_GUIDELINES.md §9) that could actually hurt somebody.
  * Loading on startup would mean a transcription edit takes effect on the next restart,
    with no record of who ran it or what changed. Running it on purpose produces a
    LabelSyncResult you can read.

Safe to re-run: unchanged entries are no-ops, changed entries append a superseding row.
"""
from __future__ import annotations

from app import crud
from app.database import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        result = crud.sync_transcribed_labels(db)
    finally:
        db.close()

    print(
        f"transcribed entries: {result.transcribed_entries}\n"
        f"products created:    {result.products_created}\n"
        f"records created:     {result.records_created}\n"
        f"  of which revisions:{result.records_superseded}\n"
        f"unchanged:           {result.unchanged}"
    )
    for note in result.notes:
        print(f"note: {note}")
    if result.transcribed_entries == 0:
        print(
            "\napp/label_table.TRANSCRIBED_LABEL_USES is empty, so no label data was "
            "loaded and every label-dependent check will keep reporting that it did not "
            "run. That is the intended state until values are transcribed from a primary "
            "label document with their citation — see that module's docstring."
        )


if __name__ == "__main__":
    main()
