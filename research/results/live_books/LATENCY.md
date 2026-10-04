# Live book recorder: detector latency

Window: 2026-10-04 04:03:20 UTC to 2026-10-04 04:21:45 UTC (18.4 min). Detector implementation in the logged decisions: cpp 58,610.

**These decisions use a stale reference.** Outside the US regular session the reference probability is the option-implied probability at the last regular-session close, and every such decision is flagged `reference_stale=true`. Weekend numbers are a latency demonstration of the recorder and detector, not a trading result. No order is ever sent.

## Latency per book update (microseconds)

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| receive to decision (t2 - t0) | 39.0 | 181.0 | 3,875.9 | 6,330.6 | 168.8 |
| receive to parsed (t1 - t0) | 15.0 | 59.0 | 2,799.0 | 3,162.0 | 92.0 |
| parsed to decision (t2 - t1) | 20.0 | 105.0 | 1,450.0 | 4,238.3 | 76.8 |

t0 is `time.time_ns()` when the websocket frame is handed to the handler, t1 after `json.loads`, t2 after the book update and the detector call for that asset. A frame that carries several book events is parsed once, so its later events include the earlier events' processing. Network latency from Polymarket to this machine is not included.

## Detector call cost (isolated, one book touch, nanoseconds per call)

| implementation | ns per call |
|---|---:|
| C++ `hedgecore::stale_quote` through the pybind11 module `hedgecore_stale` | 158 |
| pure-Python twin `live_books.detector.decide_py` | 290 |

The C++ figure includes the pybind11 call and tuple return; the hot path inside C++ does no allocation. Most of the receive-to-decision time is Python JSON parsing and book bookkeeping, not the decision itself.

## Throughput and decisions

- Websocket messages in the window: 28,713 (26.00 per second); messages that produced a book decision: 28,712.
- Book-update decisions: 58,610 (53.06 per second); with a usable reference: 41,332; flagged reference_stale: 58,610; fresh: 0.
- Would-trade flags (|book touch - reference| >= 5 pt toward the options): 438 (buy YES 0, buy NO 438) on 1 markets; with a fresh reference: 0; fresh and inside the forward_monday window: 0.

A flag is counted on every book update while the touch stays through the threshold, so flags are not trades and repeat for one standing quote.

Files still open or truncated when read: 1; unreadable lines: 0.
