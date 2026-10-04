from __future__ import annotations

import numpy as np

from . import config as cfg


def fee(p, rate: float, exponent: float, c: float = 1.0):
    p = np.asarray(p, dtype=float)
    return np.where((p > 0) & (p < 1), c * rate * (p * (1.0 - p)) ** exponent, 0.0)


def pair_arb(bids_a: list[tuple[float, float]], asks_b: list[tuple[float, float]], fa: tuple[float, float], fb: tuple[float, float]) -> dict:
    i = j = 0
    ra, rb = (list(bids_a[0]) if bids_a else None), (list(asks_b[0]) if asks_b else None)
    size = locked = 0.0
    best = float("nan")
    while ra is not None and rb is not None:
        e = ra[0] - rb[0] - float(fee(ra[0], *fa)) - float(fee(rb[0], *fb))
        if best != best:
            best = e
        if e <= 0:
            break
        q = min(ra[1], rb[1])
        size, locked = size + q, locked + q * e
        ra[1] -= q
        rb[1] -= q
        if ra[1] <= 1e-12:
            i += 1
            ra = list(bids_a[i]) if i < len(bids_a) else None
        if rb[1] <= 1e-12:
            j += 1
            rb = list(asks_b[j]) if j < len(asks_b) else None
    return {"size": size, "locked": locked, "edge": best}


def basket_arb(books: list[list[tuple[float, float]]], fees: list[tuple[float, float]], side: str) -> dict:
    lv = [[list(x) for x in b] for b in books]
    if not lv or any(not b for b in lv):
        return {"size": 0.0, "locked": 0.0, "edge": float("nan")}
    idx = [0] * len(lv)
    size = locked = 0.0
    best = float("nan")
    while True:
        px = [lv[k][idx[k]][0] for k in range(len(lv))]
        f = sum(float(fee(p, *fees[k])) for k, p in enumerate(px))
        e = (1.0 - sum(px) - f) if side == "buy_yes" else (sum(px) - 1.0 - f)
        if best != best:
            best = e
        if e <= 0:
            break
        q = min(lv[k][idx[k]][1] for k in range(len(lv)))
        size, locked = size + q, locked + q * e
        done = False
        for k in range(len(lv)):
            lv[k][idx[k]][1] -= q
            if lv[k][idx[k]][1] <= 1e-12:
                idx[k] += 1
                if idx[k] >= len(lv[k]):
                    done = True
        if done:
            break
    return {"size": size, "locked": locked, "edge": best}


def pair_edge(mid_a, mid_b, h: float, fa: tuple[float, float], fb: tuple[float, float], c: float = 1.0):
    lo, hi = cfg.PRICE_CLIP
    a = np.clip(np.asarray(mid_a, float) - c * h, lo, hi)
    b = np.clip(np.asarray(mid_b, float) + c * h, lo, hi)
    return a - fee(a, *fa, c) - b - fee(b, *fb, c)


def basket_edge(mids: np.ndarray, h: float, fees: list[tuple[float, float]], c: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    lo, hi = cfg.PRICE_CLIP
    ask = np.clip(mids + c * h, lo, hi)
    bid = np.clip(mids - c * h, lo, hi)
    fa = np.vstack([fee(ask[k], *fees[k], c) for k in range(len(fees))])
    fb = np.vstack([fee(bid[k], *fees[k], c) for k in range(len(fees))])
    return 1.0 - ask.sum(0) - fa.sum(0), bid.sum(0) - 1.0 - fb.sum(0)


def episodes(flag: np.ndarray, t: np.ndarray, gap_s: float = cfg.EPISODE_GAP_S) -> list[tuple[int, int]]:
    idx = np.flatnonzero(flag)
    if not len(idx):
        return []
    out = [[idx[0], idx[0]]]
    for i in idx[1:]:
        if t[i] - t[out[-1][1]] <= gap_s:
            out[-1][1] = i
        else:
            out.append([i, i])
    return [(a, b) for a, b in out]


def jumps(t: np.ndarray, p: np.ndarray, points: float = cfg.JUMP_POINTS, window: float = cfg.JUMP_WINDOW_S,
          cooldown: float = cfg.JUMP_COOLDOWN_S) -> list[tuple[int, float]]:
    k = int(round(window / 60))
    if len(p) <= k:
        return []
    d = (p[k:] - p[:-k]) * 100
    cand = np.flatnonzero(np.abs(np.nan_to_num(d)) >= points - 1e-9) + k
    out, last = [], -np.inf
    for i in cand:
        if t[i] - last >= cooldown:
            out.append((int(i), float((p[i] - p[i - k]) * 100)))
            last = t[i]
    return out


def taker_trade(p_in: float, p_out: float, up: bool, h: float, f: tuple[float, float], c: float) -> tuple[float, float]:
    lo, hi = cfg.PRICE_CLIP
    if up:
        e, x = min(p_in + c * h, hi), max(p_out - c * h, lo)
        return e, x - e - float(fee(e, *f, c)) - float(fee(x, *f, c))
    e, x = max(p_in - c * h, lo), min(p_out + c * h, hi)
    return e, e - x - float(fee(e, *f, c)) - float(fee(x, *f, c))
