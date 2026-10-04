# Live book recorder: detector latency

Window: 2026-10-04 04:03:20 UTC to 2026-10-04 10:23:24 UTC (380.1 min). Detector implementation in the logged decisions: cpp 548,990, cpp_book 361,098, native_ws_spin 25,918.

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

**new path with keep-warm (interactive QoS, one native thread spinning to keep the P cores awake)** (`cpp_book+warm`), 2026-10-04 07:39:23 UTC to 2026-10-04 10:11:52 UTC (152.5 min), 333,414 decisions.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| receive to decision (t2 - t0) | 5.17 | 19.75 | 84.74 | 2,266.46 | 17.54 |
| receive to parsed (t1 - t0) | 5.04 | 19.46 | 83.22 | 2,265.17 | 17.35 |
| parsed to decision (t2 - t1) | 0.08 | 0.33 | 1.12 | 4.62 | 0.19 |

**native path, busy-polling the sockets, engine kept in cache by rerunning the last frame when idle** (`native_ws_spin+warm`), 2026-10-04 10:11:56 UTC to 2026-10-04 10:23:24 UTC (11.5 min), 25,918 decisions.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| socket to decision (t2 - ts) | 19.21 | 51.71 | 263.99 | 4,677.41 | 51.48 |
| recv return to decision (t2 - tv) | 6.71 | 19.92 | 307.75 | 4,664.66 | 40.35 |
| after TLS read to decision (t2 - tr) | 1.71 | 10.29 | 223.91 | 4,657.82 | 32.23 |
| receive to decision (t2 - t0) | 1.12 | 8.83 | 187.41 | 4,650.47 | 28.96 |
| receive to parsed (t1 - t0) | 1.08 | 8.75 | 187.37 | 4,650.47 | 28.90 |
| parsed to decision (t2 - t1) | 0.04 | 0.12 | 0.33 | 0.67 | 0.06 |

t0 is `time.time_ns()` when the websocket frame is handed to the handler. Old path: t1 after `json.loads` (and after the gzip write of the raw frame, which came first), t2 after the dict book update and the detector call for that token, both from `time.time_ns()`. New path: the frame bytes go to `hedgecore_book.BookEngine.process` in one call; t1 is when that event's book update is done and t2 when its decision is written, both read inside C++ from the monotonic clock that `time.perf_counter_ns()` uses and placed on t0's wall clock by the offset from a `perf_counter_ns()` read taken at receive, so sub-microsecond intervals are resolved; the raw gzip write now happens after the decisions. A frame that carries several book events is handled in one pass, so its later events include the earlier events' processing. Network latency from Polymarket to this machine is not included.

Native path: one C++ thread owns the sockets, the OpenSSL sessions and the websocket framing and calls the engine directly, so no Python runs between the socket and the decision; Python only drains the finished frames and decisions for logging. ts is the monotonic clock just before the `SSL_read` call that returned the frame's bytes (with busy polling this is within one poll iteration, about 0.2 us, of the bytes becoming readable; macOS gives no kernel receive timestamps for TCP), tv is when the underlying `recv` returned them, tr is after TLS decryption and t0 is after the websocket frame is decoded, all placed on the wall clock like t1 and t2. On the Python paths tr is taken in the websockets protocol's `data_received` callback, after asyncio's TLS layer has decrypted the bytes; the Python paths have no ts or tv. A frame that arrives in the same read as an earlier one shares its ts, tv and tr. Each path's window starts with a subscription snapshot (two frames of 200 books each); in a short window those decisions set the p99, which is why the concurrent A/B below drops the first 30 s.

## Concurrent A/B (microseconds per book update)

The recorders below ran at the same time on this machine, each with its own connections to the same 400 tokens, so they saw the same market traffic and the same machine load. Common window 2026-10-04 09:55:22 UTC to 2026-10-04 10:06:27 UTC (11.1 min), starting 30 s after the later start so that no subscription snapshot is in it.

| path | stage | n | p50 | p90 | p99 | p99.9 | mean |
|---|---|---:|---:|---:|---:|---:|---:|
| `native_ws_spin+warm` | socket to decision (t2 - ts) | 30,206 | 15.48 | 46.15 | 160.87 | 1,894.02 | 27.07 |
| `native_ws_spin+warm` | recv return to decision (t2 - tv) | 30,206 | 5.56 | 18.83 | 56.08 | 1,399.83 | 13.42 |
| `native_ws_spin+warm` | after TLS read to decision (t2 - tr) | 30,206 | 1.50 | 8.83 | 26.62 | 1,123.18 | 6.48 |
| `native_ws_spin+warm` | receive to decision (t2 - t0) | 30,206 | 0.83 | 6.31 | 19.54 | 667.06 | 3.96 |
| `cpp_book+warm` | after TLS read to decision (t2 - tr) | 30,204 | 91.42 | 240.88 | 855.66 | 3,131.53 | 138.61 |
| `cpp_book+warm` | receive to decision (t2 - t0) | 30,204 | 6.67 | 19.54 | 46.00 | 634.81 | 11.71 |

## Replay benchmark on the recorded frames (microseconds per frame)

Closed raw files raw_20261004T04.jsonl.gz to raw_20261004T09.jsonl.gz: 436,576 frames, 875,714 decisions against synthetic references (drawn per market so that both sides and the no-reference case occur, with reference changes and token removal and re-adding during the replay). Decisions that differ between the two paths (side, prices and sizes exact, edges to 1e-9): 0 frames.

| path | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| old: `json.loads`, dict books, C++ detector call per token | 4.00 | 4.33 | 5.62 | 14.18 | 4.12 |
| new: one `BookEngine.process` call | 0.58 | 0.71 | 0.96 | 2.58 | 0.62 |
| new, receive to decision inside C++ (t2 - t0), per decision | 0.58 | 0.67 | 0.96 | 89.52 | 0.81 |

Both paths run in one process on the same frames, timed with `time.perf_counter_ns()` around the call; the raw gzip write is excluded from both. The per-decision tail of the new path comes from the subscription snapshot frames, which carry 200 books each.

## Native client on the recorded frames (loopback replay)

The same closed raw files served over a local plain websocket to the native client (busy polling, rerun warming on): 436,576 frames sent, 436,576 received, 0 with different bytes; 875,714 decisions, frames whose decisions differ from `BookEngine.process` on the same bytes: 0.

| stage | p50 | p90 | p99 | p99.9 | mean |
|---|---:|---:|---:|---:|---:|
| loopback socket to decision (t2 - ts) | 6.71 | 8.92 | 19.21 | 297.85 | 8.32 |
| frame decoded to decision (t2 - t0) | 0.38 | 0.50 | 1.33 | 108.68 | 1.06 |

The server writes frames as fast as it can, so several frames often arrive in one read and share its ts; the later ones include the earlier ones' processing.

## Detector call cost (isolated, one book touch, nanoseconds per call)

| implementation | ns per call |
|---|---:|
| C++ `hedgecore::stale_quote` through the pybind11 module `hedgecore_stale` | 208 |
| pure-Python twin `live_books.detector.decide_py` | 292 |

The C++ figure includes the pybind11 call and tuple return. In the old path most of the receive-to-decision time is Python JSON parsing and book bookkeeping, not the decision itself; the new path moves the parse, the books and the decision into one C++ call that does no allocation once its buffers are warm.

## Throughput and decisions

- Websocket messages in the window: 466,524 (20.46 per second); messages that produced a book decision: 466,336.
- Book-update decisions: 936,006 (41.05 per second); with a usable reference: 623,182; flagged reference_stale: 936,006; fresh: 0.
- Would-trade flags (|book touch - reference| >= 5 pt toward the options): 9,103 (buy YES 0, buy NO 9,103) on 4 markets; with a fresh reference: 0; fresh and inside the forward_monday window: 0.

A flag is counted on every book update while the touch stays through the threshold, so flags are not trades and repeat for one standing quote.

Files still open or truncated when read: 1; unreadable lines: 0.
