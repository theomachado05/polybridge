import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "research" / "tests" / "fakes.py"
_spec = importlib.util.spec_from_file_location("research_fakes", _path)
research_fakes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research_fakes)
