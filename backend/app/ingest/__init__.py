"""Outside data reaching a decision, auditably.

The package is split so that the parts which can be reasoned about without a database
are physically separate from the parts that cannot:

    base.py     PURE  the adapter protocol, the stage vocabulary, the status enum
    domains.py  PURE  the 17-domain registry and the MVP/finance boundary
    registry.py PURE  source_key -> SourceDescriptor
    geo.py      PURE  haversine_km
    pipeline.py       the ONLY module here that touches the database
    cimis.py          the ONLY module here that makes a network call

`tests/test_ingest_registry.py` pins that separation. It is not a style preference: the
pure modules are what let the domain boundary and the abstention rules be tested without
a session, and a stray `from app import crud` in one of them would make the guarantee a
matter of discipline rather than construction.
"""
from app.ingest import base, domains, geo, registry  # noqa: F401
