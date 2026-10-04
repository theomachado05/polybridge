"""Forward tests (rules frozen): the ladder live check and the touch_fresh forward procedure, wired to the recorder.

The rules live in ``research/ladder_replay`` and ``research/touch_fresh`` and are called, never copied or edited. Every
output goes under ``backend/data_forward/`` (override: ``POLYBRIDGE_FORWARD_DIR``), never under ``research/results/``.
"""
