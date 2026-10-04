from __future__ import annotations

SET_A_LISTED = ("2024-01-01", "2025-09-30")
SET_A_MIN_VOLUME = 50_000.0
SET_B_LISTED = ("2025-10-01", "2026-10-03")
SET_B_VOLUME = (10_000.0, 50_000.0)
YES_NO = ["Yes", "No"]

CAT_PAGE = 100
CAT_MAX_PAGES = {"a": 60, "b": 380}
CAT_OFFSET_CAP = 2000
CAT_STOP_EVENT_VOLUME = {"a": 100_000.0, "b": 20_000.0}

RATE = 1.0
SLOW_RATE = 0.5
MAX_REQUESTS = 3000
MAX_PRINT_REQUESTS = 2400
PRINT_REQUESTS_PER_SET = 1200
RESULT_BATCH = 60
PULL_DEADLINE_ET = "2026-10-04 03:40"
PRINT_PAGE, PRINT_PAGES = 10_000, 2
RECORDER_LOG = "forward/recorder.log"
RECORDER_CHECK_EVERY = 20
RECORDER_MAX_NEW_FAILS = 5
RECORDER_PAUSE_S = 120

WINDOW_S = 600
WINDOW_VARIANT_S = 120

HAIRCUT = 0.01
SIZE_CAP = 100.0
PRICE_CLIP = (0.001, 0.999)
COSTS = {1.0: {"fee_mult": 1.0, "haircut": 0.01},
         2.0: {"fee_mult": 2.0, "haircut": 0.02}}

OOS_SHARE = 0.20
CALENDAR_OOS_START = {"a": "2025-05-26",
                      "b": "2026-07-22"}

N_BOOT, BOOT_SEED = 2000, 24

MIN_OOS_TRADES, MIN_OOS_DATES = 30, 10

SECONDARY_ROWS = ("year check",
                  "corrected rule",
                  "corrected rule, unseen sample",
                  "registered rule, unseen sample")
PARTNER_COMMIT = "4d9ac93"
CREATION_TOLERANCE_S = 60
TEXT_BATCH = 60
