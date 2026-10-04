"""Golden lock on the catalog of the 17 families that predate the micro families: every key that existed in
manifest.json before them must stay identical (the micro families live under their own keys)."""

import json
from pathlib import Path

import hedgecore

GOLDEN = Path(__file__).resolve().parent / "golden" / "manifest_17_families.json"


def test_pre_existing_catalog_keys_unchanged():
    golden = json.loads(GOLDEN.read_text())
    now = hedgecore.catalog()
    for key, want in golden.items():
        assert json.loads(json.dumps(now[key], allow_nan=False)) == want, key
