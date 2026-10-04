import json
from pathlib import Path

import hedgecore

GOLDEN = Path(__file__).resolve().parent / "golden" / "manifest_17_families.json"


def test_pre_existing_catalog_keys_unchanged():
    golden = json.loads(GOLDEN.read_text())
    now = hedgecore.catalog()
    for key, want in golden.items():
        assert json.loads(json.dumps(now[key], allow_nan=False)) == want, key
