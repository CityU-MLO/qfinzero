"""Load-only ingest glue: raw drops -> ESP stores (Mongo / SQLite).

Convert-only orchestration reuses these to flip news/econ/earnings sources from
raw into the stores ESP serves, without re-downloading.
"""
