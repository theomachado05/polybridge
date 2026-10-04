import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[2] / "arb" / "tests" / "synth.py"
_spec = importlib.util.spec_from_file_location("_arb_synth_impl", _p)
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)
bs_call, true_prob, make_chain = _m.bs_call, _m.true_prob, _m.make_chain
