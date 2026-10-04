# Live book recorder: detector latency

Window: 2026-10-04 04:03:20 UTC to 2026-10-04 07:50:52 UTC (227.5 min). Detector implementation in the logged decisions: cpp 548,990, cpp_book 52,662.

**These decisions use a stale reference.** Outside the US regular session the reference probability is the option-implied probability at the last regular-session close, and every such decision is flagged `reference_stale=true`. Weekend numbers are a latency demonstration of the recorder and detector, not a trading result. No order is ever sent.

## Live latency per book update (microseconds)

**old path: Python json.loads and dict books, C++ detector call per token** (`cpp`), 2026-10-04 04:03:20 UTC to 2026-10-04 07:28:23 UTC (205.0 min), 548,990 decisions.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| receive to decision (t2 - t0) | 40.00 | 178.00 | 1,805.00 | 9,171.02 | 130.45 |
| receive to parsed (t1 - t0) | 16.00 | 59.00 | 857.00 | 5,266.00 | 59.81 |
| parsed to decision (t2 - t1) | 21.00 | 104.00 | 846.00 | 5,226.07 | 70.64 |

**new path: one C++ call per frame (simdjson parse, books, detector)** (`cpp_book`), 2026-10-04 07:28:31 UTC to 2026-10-04 07:39:20 UTC (10.8 min), 27,684 decisions.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| receive to decision (t2 - t0) | 7.92 | 33.79 | 449.57 | 1,386.62 | 25.31 |
| receive to parsed (t1 - t0) | 7.71 | 33.12 | 418.79 | 1,386.16 | 25.00 |
| parsed to decision (t2 - t1) | 0.12 | 0.58 | 1.62 | 6.60 | 0.31 |

**new path with keep-warm (interactive QoS, one native thread spinning to keep the P cores awake)** (`cpp_book+warm`), 2026-10-04 07:39:23 UTC to 2026-10-04 07:50:52 UTC (11.5 min), 24,978 decisions.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| receive to decision (t2 - t0) | 3.42 | 17.04 | 340.73 | 2,254.96 | 27.12 |
| receive to parsed (t1 - t0) | 3.33 | 16.85 | 340.54 | 2,254.96 | 27.00 |
| parsed to decision (t2 - t1) | 0.04 | 0.25 | 0.92 | 2.88 | 0.11 |

t0 is `time.time_ns()` when the websocket frame is handed to the handler. Old path: t1 after `json.loads` (and after the gzip write of the raw frame, which came first), t2 after the dict book update and the detector call for that token, both from `time.time_ns()`. New path: the frame bytes go to `hedgecore_book.BookEngine.process` in one call; t1 is when that event's book update is done and t2 when its decision is written, both read inside C++ from the monotonic clock that `time.perf_counter_ns()` uses and placed on t0's wall clock by the offset from a `perf_counter_ns()` read taken at receive, so sub-microsecond intervals are resolved; the raw gzip write now happens after the decisions. A frame that carries several book events is handled in one pass, so its later events include the earlier events' processing. Network latency from Polymarket to this machine is not included.

## Replay benchmark on the recorded frames (microseconds per frame)

Closed raw files raw_20261004T04.jsonl.gz to raw_20261004T06.jsonl.gz: 236,510 frames, 474,600 decisions against synthetic references (drawn per market so that both sides and the no-reference case occur, with reference changes and token removal and re-adding during the replay). Decisions that differ between the two paths (side, prices and sizes exact, edges to 1e-9): 0 frames.

| path | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| old: `json.loads`, dict books, C++ detector call per token | 4.08 | 4.42 | 5.62 | 12.92 | 4.21 |
| new: one `BookEngine.process` call | 0.58 | 0.67 | 0.96 | 2.54 | 0.62 |
| new, receive to decision inside C++ (t2 - t0), per decision | 0.54 | 0.67 | 0.96 | 89.55 | 0.82 |

Both paths run in one process on the same frames, timed with `time.perf_counter_ns()` around the call; the raw gzip write is excluded from both. The per-decision tail of the new path comes from the subscription snapshot frames, which carry 200 books each.

## Detector call cost (isolated, one book touch, nanoseconds per call)

| implementation | ns per call |
|---|---:|
| C++ `hedgecore::stale_quote` through the pybind11 module `hedgecore_stale` | 148 |
| pure-Python twin `live_books.detector.decide_py` | 288 |

The C++ figure includes the pybind11 call and tuple return. In the old path most of the receive-to-decision time is Python JSON parsing and book bookkeeping, not the decision itself; the new path moves the parse, the books and the decision into one C++ call that does no allocation once its buffers are warm.

## Throughput and decisions

- Websocket messages in the window: 299,644 (21.95 per second); messages that produced a book decision: 299,641.
- Book-update decisions: 601,652 (44.07 per second); with a usable reference: 415,966; flagged reference_stale: 601,652; fresh: 0.
- Would-trade flags (|book touch - reference| >= 5 pt toward the options): 4,282 (buy YES 0, buy NO 4,282) on 3 markets; with a fresh reference: 0; fresh and inside the forward_monday window: 0.

A flag is counted on every book update while the touch stays through the threshold, so flags are not trades and repeat for one standing quote.

Files still open or truncated when read: 1; unreadable lines: 0.
