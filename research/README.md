# PolyBridge research · Trade the 8-K

Pre-registration: [HYPOTHESIS.md](HYPOTHESIS.md) (19:38 ET, 2 Oct 2026) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md) (20:08 ET), both committed before any event data was fetched.

Every result of every study, with its source file: [EVIDENCE.md](EVIDENCE.md). How the product gates on them: [../docs/design.md](../docs/design.md), section 6.

## Reproduce (Python 3.10+, only a Massive API key)

```bash
cd research
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # run from inside research/: the file uses `-e .`
echo "MASSIVE_API_KEY=<your key>" > .env
jupyter nbconvert --to notebook --execute polybridge_8k.ipynb --ExecutePreprocessor.timeout=7200
```

Pin `LAST_SESSION` in the same cell at the method freeze (the run date of the single out-of-sample run). Judges: edit `START, END` in the first code cell to your sealed window and rerun all cells. Timing is frozen to the conservative rule: every filing is treated as public after the close (no lookahead); EDGAR acceptance times are not used by the notebook.
