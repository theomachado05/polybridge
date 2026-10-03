# PolyBridge research · Trade the 8-K

Pre-registration: [HYPOTHESIS.md](HYPOTHESIS.md) (19:38 ET, 2 Oct 2026) and [HYPOTHESIS_TAGS.md](HYPOTHESIS_TAGS.md) (20:08 ET), both committed before any event data was fetched.

## Reproduce (Python 3.10+, only a Massive API key)

```bash
cd research
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "MASSIVE_API_KEY=<your key>" > .env
jupyter nbconvert --to notebook --execute polybridge_8k.ipynb --ExecutePreprocessor.timeout=7200
```

Judges: edit `START, END` in the first code cell to your sealed window and rerun all cells. Optional: set `SEC_USER_AGENT="Name email"` to use EDGAR acceptance times; without it every filing is treated as public after the close (no lookahead).
