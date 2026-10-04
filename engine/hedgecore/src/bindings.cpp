#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cmath>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>

#include "hedgecore/engine.hpp"
#include "hedgecore/library.hpp"
#include "hedgecore/micro.hpp"
#include "hedgecore/replay.hpp"

namespace py = pybind11;
using namespace hedgecore;

namespace {

py::object nan_none(double x) { return std::isfinite(x) ? py::object(py::float_(x)) : py::object(py::none()); }

const FamilyInfo& family_or_throw(const std::string& id) {
  const FamilyInfo* f = find_family(id);
  if (!f) throw py::value_error("unknown algo family: " + id);
  return *f;
}

Params params_from(const FamilyInfo& f, const py::dict& d) {
  Params p = f.spec.defaults();
  for (auto kv : d) {
    const auto name = py::cast<std::string>(kv.first);
    const int i = f.spec.index_of(name);
    if (i < 0) throw py::key_error("family " + std::string(f.id) + " has no param '" + name + "'");
    p.v[static_cast<std::size_t>(i)] = py::cast<double>(kv.second);
  }
  return p;
}

py::dict params_dict(const FamilyInfo& f, const Params& p) {
  py::dict d;
  for (int i = 0; i < f.spec.n; ++i)
    d[f.spec.defs[static_cast<std::size_t>(i)].name] = p.v[static_cast<std::size_t>(i)];
  return d;
}

Position position_from(const py::dict& d) {
  Position p;
  for (auto kv : d) {
    const auto k = py::cast<std::string>(kv.first);
    const double v = py::cast<double>(kv.second);
    if (k == "equity") p.equity = v;
    else if (k == "pred_yes") p.pred_yes = v;
    else if (k == "pred_no") p.pred_no = v;
    else if (k == "option") p.option = v;
    else if (k == "shares_held") p.shares_held = v;
    else throw py::key_error("unknown position field '" + k + "'");
  }
  return p;
}

FeeModel fees_from(const std::optional<py::dict>& d) {
  FeeModel f;
  if (!d) return f;
  for (auto kv : *d) {
    const auto k = py::cast<std::string>(kv.first);
    const double v = py::cast<double>(kv.second);
    if (k == "equity_per_share") f.equity_per_share = v;
    else if (k == "equity_min_per_order") f.equity_min_per_order = v;
    else if (k == "equity_half_spread") f.equity_half_spread = v;
    else if (k == "option_per_contract") f.option_per_contract = v;
    else if (k == "option_multiplier") f.option_multiplier = v;
    else if (k == "option_half_spread") f.option_half_spread = v;
    else if (k == "poly_taker_rate") f.poly_taker_rate = v;
    else if (k == "kalshi_coef") f.kalshi_coef = v;
    else if (k == "other_venue_half_spread") f.other_venue_half_spread = v;
    else throw py::key_error("unknown fee field '" + k + "'");
  }
  return f;
}

Venue venue_from(const py::handle& h) {
  if (py::isinstance<py::str>(h)) {
    const auto s = py::cast<std::string>(h);
    if (s == "poly" || s == "polymarket") return Venue::Poly;
    if (s == "kalshi") return Venue::Kalshi;
    throw py::value_error("venue must be 'poly' or 'kalshi'");
  }
  return py::cast<int>(h) == 1 ? Venue::Kalshi : Venue::Poly;
}

Instrument instrument_from(const std::string& s) {
  if (s == "equity") return Instrument::Equity;
  if (s == "pred_yes") return Instrument::PredYes;
  if (s == "pred_no") return Instrument::PredNo;
  if (s == "option") return Instrument::Option;
  throw py::value_error("instrument must be equity | pred_yes | pred_no | option");
}

bool flip_from(const std::string& direction) {
  if (direction == "down_on_yes") return false;
  if (direction == "up_on_yes") return true;
  throw py::value_error("direction must be 'down_on_yes' or 'up_on_yes'");
}

bool flip_for(const FamilyInfo& f, const std::string& direction) {
  const bool flip = flip_from(direction);
  if (flip && std::string_view(f.division) != "hedge")
    throw py::value_error(std::string("direction='up_on_yes' applies only to hedge-division families; '") + f.id +
                          "' is division '" + f.division + "' (its intents name the real YES/NO contract)");
  return flip;
}

Position oriented(Position p, bool flip) noexcept {
  if (flip) std::swap(p.pred_yes, p.pred_no);
  return p;
}

struct Field {
  const char* name;
  double MarketTick::*ptr;
};
const Field kFields[] = {{"yes_bid", &MarketTick::yes_bid},
                         {"yes_ask", &MarketTick::yes_ask},
                         {"no_bid", &MarketTick::no_bid},
                         {"no_ask", &MarketTick::no_ask},
                         {"p_other_venue", &MarketTick::p_other_venue},
                         {"under_px", &MarketTick::under_px},
                         {"under_bid", &MarketTick::under_bid},
                         {"under_ask", &MarketTick::under_ask},
                         {"opt_mid", &MarketTick::opt_mid},
                         {"opt_delta", &MarketTick::opt_delta},
                         {"opt_iv", &MarketTick::opt_iv},
                         {"opt_implied_prob", &MarketTick::opt_implied_prob},
                         {"eightk_score", &MarketTick::eightk_score}};

double* book_field(MarketTick& t, const std::string& k) {
  if (k.size() < 8) return nullptr;
  const char last = k.back();
  if (last < '0' || last > '4' || k[k.size() - 2] != '_') return nullptr;
  const int i = last - '0';
  const std::string stem = k.substr(0, k.size() - 2);
  if (stem == "bid_px") return &t.bids[i].px;
  if (stem == "bid_qty") return &t.bids[i].qty;
  if (stem == "ask_px") return &t.asks[i].px;
  if (stem == "ask_qty") return &t.asks[i].qty;
  return nullptr;
}

double* scalar_field(MarketTick& t, const std::string& k) {
  for (const auto& f : kFields)
    if (k == f.name) return &(t.*(f.ptr));
  return book_field(t, k);
}

double to_double_or_nan(const py::handle& h) { return h.is_none() ? kNaN : py::cast<double>(h); }

MarketTick tick_from(const py::dict& d) {
  MarketTick t;
  for (auto kv : d) {
    const auto k = py::cast<std::string>(kv.first);
    if (k == "ts_ns") { t.ts_ns = py::cast<std::int64_t>(kv.second); continue; }
    if (k == "venue") { t.venue = venue_from(kv.second); continue; }
    double* f = scalar_field(t, k);
    if (!f) throw py::key_error("unknown tick field '" + k + "'");
    *f = to_double_or_nan(kv.second);
  }
  return t;
}

using DArr = py::array_t<double, py::array::c_style | py::array::forcecast>;
using IArr = py::array_t<std::int64_t, py::array::c_style | py::array::forcecast>;

std::vector<MarketTick> ticks_from(const py::dict& d) {
  if (!d.contains("ts_ns")) throw py::key_error("ticks need a 'ts_ns' array");
  const IArr ts = py::cast<IArr>(d["ts_ns"]);
  const auto n = static_cast<std::size_t>(ts.size());
  std::vector<MarketTick> v(n);
  for (std::size_t i = 0; i < n; ++i) v[i].ts_ns = ts.data()[i];
  for (auto kv : d) {
    const auto k = py::cast<std::string>(kv.first);
    if (k == "ts_ns") continue;
    if (k == "venue") {
      if (py::isinstance<py::str>(kv.second) || py::isinstance<py::int_>(kv.second)) {
        const Venue ven = venue_from(kv.second);
        for (auto& t : v) t.venue = ven;
      } else {
        const IArr a = py::cast<IArr>(kv.second);
        if (static_cast<std::size_t>(a.size()) != n) throw py::value_error("ticks['venue'] length differs from ts_ns");
        for (std::size_t i = 0; i < n; ++i) v[i].venue = a.data()[i] == 1 ? Venue::Kalshi : Venue::Poly;
      }
      continue;
    }
    MarketTick probe;
    double* pf = scalar_field(probe, k);
    if (!pf) throw py::key_error("unknown tick field '" + k + "'");
    const auto off = reinterpret_cast<const char*>(pf) - reinterpret_cast<const char*>(&probe);
    const DArr a = py::cast<DArr>(kv.second);
    if (static_cast<std::size_t>(a.size()) != n) throw py::value_error("ticks['" + k + "'] length differs from ts_ns");
    for (std::size_t i = 0; i < n; ++i)
      *reinterpret_cast<double*>(reinterpret_cast<char*>(&v[i]) + off) = a.data()[i];
  }
  return v;
}

py::dict intent_dict(const Intent& i) {
  py::dict d;
  d["action"] = i.action == Action::Order ? "order" : "hold";
  d["instrument"] = to_string(i.instrument);
  d["side"] = i.side;
  d["qty"] = i.qty;
  d["limit_px"] = nan_none(i.limit_px);
  d["reason"] = reason_name(i.reason);
  d["reason_code"] = i.reason;
  d["reason_block"] = reason_block(i.reason);
  d["signal"] = nan_none(i.signal);
  d["latency_ns"] = i.latency_ns;
  d["venue"] = to_string(i.venue);
  return d;
}

py::dict stats_dict(const ReplayStats& s) {
  py::dict d;
  d["n_ticks"] = s.n_ticks;
  d["n_orders"] = s.n_orders;
  d["n_fills"] = s.n_fills;
  d["n_rejected"] = s.n_rejected;
  d["pnl"] = s.pnl;
  d["fees"] = s.fees;
  d["max_dd"] = s.max_dd;
  d["hedge_var_reduction"] = nan_none(s.hedge_var_reduction);
  d["hedge_var_reduction_vs_static"] = nan_none(s.hedge_var_reduction_vs_static);
  d["avg_hedge_ratio"] = nan_none(s.avg_hedge_ratio);
  d["turnover"] = s.turnover;
  d["p50_ns"] = s.p50_ns;
  d["p99_ns"] = s.p99_ns;
  return d;
}

py::list micro_families_list();

py::dict catalog_dict() {
  const Catalog& c = catalog();
  py::list fams;
  for (const auto& f : c.families) {
    py::dict fd;
    fd["id"] = f.id;
    fd["division"] = f.division;
    fd["ui_kind"] = f.ui_kind;
    fd["idea"] = f.idea;
    py::list ev, ins, blocks;
    for (const char* e : f.event_classes) ev.append(e);
    for (const char* e : f.instruments) ins.append(e);
    std::set<std::string> kinds;
    for (const auto& b : f.blocks) {
      py::dict bd;
      bd["kind"] = b.kind;
      bd["name"] = b.name;
      bd["ui_kind"] = ui_kind_of(b.kind);
      blocks.append(bd);
      kinds.insert(ui_kind_of(b.kind));
    }
    fd["event_classes"] = ev;
    fd["instruments"] = ins;
    fd["blocks"] = blocks;
    fd["ui_kinds"] = std::vector<std::string>(kinds.begin(), kinds.end());
    py::list params;
    py::dict grid;
    for (int i = 0; i < f.spec.n; ++i) {
      const auto& pd = f.spec.defs[static_cast<std::size_t>(i)];
      std::vector<double> g(pd.grid.begin(), pd.grid.begin() + pd.n_grid);
      py::dict pdict;
      pdict["name"] = pd.name;
      pdict["min"] = pd.min;
      pdict["max"] = pd.max;
      pdict["default"] = pd.def;
      pdict["grid"] = g;
      pdict["tuned"] = pd.n_grid > 1;
      pdict["help"] = pd.help;
      params.append(pdict);
      grid[pd.name] = g;
    }
    fd["params"] = params;
    fd["grid"] = grid;
    fd["preset_count"] = f.preset_count;
    fams.append(fd);
  }
  py::dict block_kinds;
  for (const char* k : {"signals", "gates", "sizers", "execution", "risk", "tax", "routing"})
    block_kinds[k] = ui_kind_of(k);
  py::dict reasons;
  for (Rc r : kAllReasons) {
    py::dict rd;
    rd["name"] = to_string(r);
    rd["block"] = reason_block(code(r));
    reasons[py::str(std::to_string(code(r)))] = rd;
  }
  py::list classes;
  for (const char* e : ev::kAll) classes.append(e);
  py::dict out;
  out["schema"] = "hedgecore.catalog/v1";
  out["total"] = c.total;
  out["n_families"] = c.families.size();
  out["event_classes"] = classes;
  out["block_kinds"] = block_kinds;
  out["reasons"] = reasons;
  out["families"] = fams;
  out["micro_families"] = micro_families_list();
  out["micro_total"] = micro_catalog().total;
  py::dict micro_reasons;
  for (Rc r : kMicroReasons) {
    py::dict rd;
    rd["name"] = to_string(r);
    rd["block"] = reason_block(code(r));
    micro_reasons[py::str(std::to_string(code(r)))] = rd;
  }
  out["micro_reasons"] = micro_reasons;
  return out;
}

struct PyAlgo {
  const FamilyInfo* info;
  Params params;
  bool flip;
  AnyAlgo algo;
  PyAlgo(const std::string& family, const py::dict& p, const py::dict& pos, const std::string& direction)
      : info(&family_or_throw(family)),
        params(params_from(*info, p)),
        flip(flip_for(*info, direction)),
        algo(make_algo(family, params, oriented(position_from(pos), flip))) {}
  py::dict tick(const py::dict& t, std::optional<std::int64_t> now_ns) {
    MarketTick mt = tick_from(t);
    if (flip) mt = flip_yes_no(mt);
    return intent_dict(on_tick(algo, mt, now_ns.value_or(mt.ts_ns)));
  }
  void fill(const std::string& inst, double qty, double px) { on_fill(algo, instrument_from(inst), qty, px); }
  void reject(const std::string& inst) { on_reject(algo, instrument_from(inst)); }
};

std::vector<MarketTick> prepared_ticks(const py::dict& ticks, bool flip) {
  std::vector<MarketTick> v = ticks_from(ticks);
  if (flip)
    for (auto& t : v) t = flip_yes_no(t);
  return v;
}

const MicroFamilyInfo& micro_or_throw(const std::string& id) {
  for (const auto& f : micro_catalog().families)
    if (id == f.id) return f;
  throw py::value_error("unknown micro family: " + id);
}

Params micro_params_from(const MicroFamilyInfo& f, const py::dict& d) {
  Params p = f.spec.defaults();
  for (auto kv : d) {
    const auto name = py::cast<std::string>(kv.first);
    const int i = f.spec.index_of(name);
    if (i < 0) throw py::key_error("family " + std::string(f.id) + " has no param '" + name + "'");
    p.v[static_cast<std::size_t>(i)] = py::cast<double>(kv.second);
  }
  return p;
}

py::dict micro_params_dict(const MicroFamilyInfo& f, const Params& p) {
  py::dict d;
  for (int i = 0; i < f.spec.n; ++i)
    d[f.spec.defs[static_cast<std::size_t>(i)].name] = p.v[static_cast<std::size_t>(i)];
  return d;
}

Tri tri_from(const py::handle& h) {
  if (h.is_none()) return Tri::Missing;
  return py::cast<bool>(h) ? Tri::True : Tri::False;
}
std::int64_t time_from(const py::handle& h) { return h.is_none() ? kNoTime : py::cast<std::int64_t>(h); }

Leg leg_from(const std::string& s) {
  if (s == "rich") return Leg::Rich;
  if (s == "cheap") return Leg::Cheap;
  throw py::value_error("leg must be 'rich' or 'cheap'");
}

const char* micro_action_name(MicroAction a) {
  switch (a) {
    case MicroAction::Hold: return "hold";
    case MicroAction::Order: return "order";
    case MicroAction::Propose: return "propose";
    case MicroAction::Cancel: return "cancel";
    case MicroAction::Unwind: return "unwind";
  }
  return "unknown";
}

LadderTick ladder_tick_from(const py::dict& d) {
  LadderTick t;
  for (auto kv : d) {
    const auto k = py::cast<std::string>(kv.first);
    const py::handle v = kv.second;
    if (k == "ts_ns") t.ts_ns = py::cast<std::int64_t>(v);
    else if (k == "bid_rich") t.bid_rich = to_double_or_nan(v);
    else if (k == "bid_rich_qty") t.bid_rich_qty = to_double_or_nan(v);
    else if (k == "ask_cheap") t.ask_cheap = to_double_or_nan(v);
    else if (k == "ask_cheap_qty") t.ask_cheap_qty = to_double_or_nan(v);
    else if (k == "fee_rate_rich") t.fee_rate_rich = to_double_or_nan(v);
    else if (k == "fee_rate_cheap") t.fee_rate_cheap = to_double_or_nan(v);
    else if (k == "tick") t.tick = to_double_or_nan(v);
    else if (k == "ts_rich_ns") t.ts_rich_ns = time_from(v);
    else if (k == "ts_cheap_ns") t.ts_cheap_ns = time_from(v);
    else if (k == "nested") t.nested = tri_from(v);
    else if (k == "event_held") t.event_held = to_double_or_nan(v);
    else throw py::key_error("unknown ladder tick field '" + k + "'");
  }
  return t;
}

TicketTick ticket_tick_from(const py::dict& d) {
  TicketTick t;
  for (auto kv : d) {
    const auto k = py::cast<std::string>(kv.first);
    const py::handle v = kv.second;
    if (k == "ts_ns") t.ts_ns = py::cast<std::int64_t>(v);
    else if (k == "bid") t.bid = to_double_or_nan(v);
    else if (k == "bid_qty") t.bid_qty = to_double_or_nan(v);
    else if (k == "ask") t.ask = to_double_or_nan(v);
    else if (k == "ref_lower") t.ref_lower = to_double_or_nan(v);
    else if (k == "ref_central") t.ref_central = to_double_or_nan(v);
    else if (k == "validated") t.validated = tri_from(v);
    else if (k == "underlying_short") t.underlying_short = to_double_or_nan(v);
    else if (k == "event_short") t.event_short = to_double_or_nan(v);
    else throw py::key_error("unknown ticket tick field '" + k + "'");
  }
  return t;
}

py::dict leg_dict(const LegOrder& l) {
  py::dict d;
  d["side"] = l.side;
  d["qty"] = l.qty;
  d["limit_px"] = nan_none(l.limit_px);
  return d;
}

py::dict pair_intent_dict(const PairIntent& i) {
  py::dict d;
  d["action"] = micro_action_name(i.action);
  d["rich"] = leg_dict(i.rich);
  d["cheap"] = leg_dict(i.cheap);
  d["cancel"] = i.action == MicroAction::Cancel ? py::object(py::str(i.cancel == Leg::Rich ? "rich" : "cheap"))
                                                : py::object(py::none());
  d["reason"] = reason_name(i.reason);
  d["reason_code"] = i.reason;
  d["reason_block"] = reason_block(i.reason);
  d["signal"] = nan_none(i.signal);
  d["latency_ns"] = i.latency_ns;
  return d;
}

py::dict ticket_intent_dict(const TicketIntent& i) {
  py::dict d;
  d["action"] = micro_action_name(i.action);
  d["side"] = i.side;
  d["qty"] = i.qty;
  d["limit_px"] = nan_none(i.limit_px);
  d["reason"] = reason_name(i.reason);
  d["reason_code"] = i.reason;
  d["reason_block"] = reason_block(i.reason);
  d["signal"] = nan_none(i.signal);
  d["latency_ns"] = i.latency_ns;
  return d;
}

template <class T>
std::vector<T> col(const py::dict& d, const char* k, std::size_t n, T missing) {
  std::vector<T> v(n, missing);
  if (!d.contains(k)) return v;
  const py::sequence s = py::cast<py::sequence>(d[k]);
  if (static_cast<std::size_t>(py::len(s)) != n) throw py::value_error(std::string("rows['") + k + "'] length differs");
  for (std::size_t i = 0; i < n; ++i) {
    const py::handle h = s[i];
    if constexpr (std::is_same_v<T, double>) v[i] = to_double_or_nan(h);
    else if constexpr (std::is_same_v<T, Tri>) v[i] = tri_from(h);
    else if constexpr (std::is_same_v<T, std::int64_t>) v[i] = time_from(h);
    else v[i] = py::cast<T>(h);
  }
  return v;
}

std::size_t rows_len(const py::dict& d, const char* key) {
  if (!d.contains(key)) throw py::key_error(std::string("rows need a '") + key + "' column");
  return static_cast<std::size_t>(py::len(d[key]));
}

std::vector<LadderRow> ladder_rows_from(const py::dict& d) {
  const std::size_t n = rows_len(d, "now_ns");
  const auto now = col<std::int64_t>(d, "now_ns", n, kNoTime);
  const auto br = col<double>(d, "bid_rich", n, kNaN), brq = col<double>(d, "bid_rich_qty", n, kNaN);
  const auto ac = col<double>(d, "ask_cheap", n, kNaN), acq = col<double>(d, "ask_cheap_qty", n, kNaN);
  const auto fr = col<double>(d, "fee_rate_rich", n, kNaN), fc = col<double>(d, "fee_rate_cheap", n, kNaN);
  const auto tk = col<double>(d, "tick", n, kNaN);
  const auto tr = col<std::int64_t>(d, "ts_rich_ns", n, kNoTime), tc = col<std::int64_t>(d, "ts_cheap_ns", n, kNoTime);
  const auto ne = col<Tri>(d, "nested", n, Tri::Missing);
  const auto pr = col<std::int64_t>(d, "pair", n, 0), ev = col<std::int64_t>(d, "event", n, 0);
  const auto yr = col<double>(d, "result_rich", n, kNaN), yc = col<double>(d, "result_cheap", n, kNaN);
  std::vector<LadderRow> v(n);
  for (std::size_t i = 0; i < n; ++i) {
    LadderRow& r = v[i];
    r.now_ns = now[i];
    r.tick.ts_ns = now[i];
    r.tick.bid_rich = br[i];
    r.tick.bid_rich_qty = brq[i];
    r.tick.ask_cheap = ac[i];
    r.tick.ask_cheap_qty = acq[i];
    r.tick.fee_rate_rich = fr[i];
    r.tick.fee_rate_cheap = fc[i];
    r.tick.tick = tk[i];
    r.tick.ts_rich_ns = tr[i];
    r.tick.ts_cheap_ns = tc[i];
    r.tick.nested = ne[i];
    r.pair = static_cast<std::uint32_t>(pr[i]);
    r.event = static_cast<std::uint32_t>(ev[i]);
    r.result_rich = yr[i];
    r.result_cheap = yc[i];
  }
  return v;
}

std::vector<TicketRow> ticket_rows_from(const py::dict& d) {
  const std::size_t n = rows_len(d, "now_ns");
  const auto now = col<std::int64_t>(d, "now_ns", n, kNoTime);
  const auto ts = d.contains("ts_ns") ? col<std::int64_t>(d, "ts_ns", n, kNoTime) : now;
  const auto bid = col<double>(d, "bid", n, kNaN), bq = col<double>(d, "bid_qty", n, kNaN);
  const auto ask = col<double>(d, "ask", n, kNaN);
  const auto lo = col<double>(d, "ref_lower", n, kNaN), ce = col<double>(d, "ref_central", n, kNaN);
  const auto va = col<Tri>(d, "validated", n, Tri::Missing);
  const auto tid = col<std::int64_t>(d, "ticket", n, 0), un = col<std::int64_t>(d, "underlying", n, 0);
  const auto ev = col<std::int64_t>(d, "event", n, 0);
  const auto out = col<double>(d, "outcome", n, kNaN);
  std::vector<TicketRow> v(n);
  for (std::size_t i = 0; i < n; ++i) {
    TicketRow& r = v[i];
    r.now_ns = now[i];
    r.tick.ts_ns = ts[i];
    r.tick.bid = bid[i];
    r.tick.bid_qty = bq[i];
    r.tick.ask = ask[i];
    r.tick.ref_lower = lo[i];
    r.tick.ref_central = ce[i];
    r.tick.validated = va[i];
    r.ticket = static_cast<std::uint32_t>(tid[i]);
    r.underlying = static_cast<std::uint32_t>(un[i]);
    r.event = static_cast<std::uint32_t>(ev[i]);
    r.outcome = out[i];
  }
  return v;
}

py::list micro_families_list() {
  py::list fams;
  for (const auto& f : micro_catalog().families) {
    py::dict fd;
    fd["id"] = f.id;
    fd["division"] = f.division;
    fd["ui_kind"] = f.ui_kind;
    fd["status"] = f.status;
    fd["idea"] = f.idea;
    py::list ev, ins, blocks, inputs;
    for (const char* e : f.event_classes) ev.append(e);
    for (const char* e : f.instruments) ins.append(e);
    for (const char* e : f.inputs) inputs.append(e);
    std::set<std::string> kinds;
    for (const auto& b : f.blocks) {
      py::dict bd;
      bd["kind"] = b.kind;
      bd["name"] = b.name;
      bd["ui_kind"] = ui_kind_of(b.kind);
      blocks.append(bd);
      kinds.insert(ui_kind_of(b.kind));
    }
    fd["event_classes"] = ev;
    fd["instruments"] = ins;
    fd["inputs"] = inputs;
    fd["blocks"] = blocks;
    fd["ui_kinds"] = std::vector<std::string>(kinds.begin(), kinds.end());
    py::list params;
    py::dict grid;
    for (int i = 0; i < f.spec.n; ++i) {
      const auto& pd = f.spec.defs[static_cast<std::size_t>(i)];
      std::vector<double> g(pd.grid.begin(), pd.grid.begin() + pd.n_grid);
      py::dict pdict;
      pdict["name"] = pd.name;
      pdict["min"] = pd.min;
      pdict["max"] = pd.max;
      pdict["default"] = pd.def;
      pdict["grid"] = g;
      pdict["tuned"] = pd.n_grid > 1;
      pdict["help"] = pd.help;
      params.append(pdict);
      grid[pd.name] = g;
    }
    fd["params"] = params;
    fd["grid"] = grid;
    fd["preset_count"] = f.preset_count;
    fams.append(fd);
  }
  return fams;
}

struct PyLadderPair {
  const MicroFamilyInfo* info;
  Params params;
  algos::LadderPair algo;
  explicit PyLadderPair(const py::dict& p)
      : info(&micro_or_throw("ladder_pair")), params(micro_params_from(*info, p)), algo(params, Position{}) {}
  py::dict tick(const py::dict& t, std::optional<std::int64_t> now_ns) {
    const LadderTick lt = ladder_tick_from(t);
    return pair_intent_dict(algo.on_tick(lt, now_ns.value_or(lt.ts_ns)));
  }
};

struct PyTouchTicket {
  const MicroFamilyInfo* info;
  Params params;
  algos::TouchTicketReference algo;
  explicit PyTouchTicket(const py::dict& p)
      : info(&micro_or_throw("touch_ticket_reference")), params(micro_params_from(*info, p)), algo(params, Position{}) {}
  py::dict tick(const py::dict& t, std::optional<std::int64_t> now_ns) {
    const TicketTick tt = ticket_tick_from(t);
    return ticket_intent_dict(algo.on_tick(tt, now_ns.value_or(tt.ts_ns)));
  }
};

}

PYBIND11_MODULE(hedgecore, m) {
  m.doc() = "PolyBridge hedgecore: the C++20 algo library (17 families), the micro families (ladder_pair, touch_ticket_reference) and the legacy Engine";

  py::class_<HedgeSpec>(m, "HedgeSpec")
      .def(py::init([](std::string ticker, double shares_held, double target_coverage, double band_shares,
                       double max_hedge_shares, std::int64_t max_staleness_ns, double sigma_k, double sigma_alpha,
                       double gap_per_share, double fee_per_share, double half_spread, double min_benefit_ratio) {
             return HedgeSpec{std::move(ticker), shares_held, target_coverage, band_shares, max_hedge_shares,
                              max_staleness_ns, sigma_k, sigma_alpha, gap_per_share, fee_per_share,
                              half_spread, min_benefit_ratio};
           }),
           py::kw_only(), py::arg("ticker"), py::arg("shares_held"), py::arg("target_coverage") = 0.5,
           py::arg("band_shares") = 10.0, py::arg("max_hedge_shares") = 0.0,
           py::arg("max_staleness_ns") = 2'000'000'000LL, py::arg("sigma_k") = 2.0, py::arg("sigma_alpha") = 0.05,
           py::arg("gap_per_share") = 0.0, py::arg("fee_per_share") = 0.0035, py::arg("half_spread") = 0.0,
           py::arg("min_benefit_ratio") = 1.0)
      .def_readwrite("ticker", &HedgeSpec::ticker)
      .def_readwrite("shares_held", &HedgeSpec::shares_held)
      .def_readwrite("target_coverage", &HedgeSpec::target_coverage)
      .def_readwrite("band_shares", &HedgeSpec::band_shares)
      .def_readwrite("max_hedge_shares", &HedgeSpec::max_hedge_shares)
      .def_readwrite("max_staleness_ns", &HedgeSpec::max_staleness_ns)
      .def_readwrite("sigma_k", &HedgeSpec::sigma_k)
      .def_readwrite("sigma_alpha", &HedgeSpec::sigma_alpha)
      .def_readwrite("gap_per_share", &HedgeSpec::gap_per_share)
      .def_readwrite("fee_per_share", &HedgeSpec::fee_per_share)
      .def_readwrite("half_spread", &HedgeSpec::half_spread)
      .def_readwrite("min_benefit_ratio", &HedgeSpec::min_benefit_ratio);

  py::class_<Decision>(m, "Decision")
      .def_property_readonly("action", [](const Decision& d) { return d.action == Action::Order ? "order" : "hold"; })
      .def_property_readonly("reason", [](const Decision& d) { return to_string(d.reason); })
      .def_readonly("order_qty", &Decision::order_qty)
      .def_readonly("target_hedge", &Decision::target_hedge)
      .def_readonly("current_hedge", &Decision::current_hedge)
      .def_readonly("latency_ns", &Decision::latency_ns);

  py::class_<Engine>(m, "Engine")
      .def(py::init<HedgeSpec>())
      .def("on_tick", [](Engine& e, std::int64_t ts_ns, double p, std::int64_t now_ns) {
             return e.on_tick(Tick{ts_ns, p}, now_ns);
           }, py::kw_only(), py::arg("ts_ns"), py::arg("p"), py::arg("now_ns"))
      .def("on_fill", &Engine::on_fill)
      .def_property_readonly("current_hedge", &Engine::current_hedge);

  m.def("catalog", &catalog_dict,
        "The compiled algo library (the manifest): families, blocks, params, grids, preset counts and the total.");
  m.def("reason_name", [](int c) { return std::string(reason_name(static_cast<std::uint16_t>(c))); });

  py::class_<PyAlgo>(m, "Algo")
      .def(py::init<const std::string&, const py::dict&, const py::dict&, const std::string&>(), py::arg("family"),
           py::arg("params") = py::dict(), py::arg("position") = py::dict(), py::arg("direction") = "down_on_yes")
      .def("on_tick", &PyAlgo::tick, py::arg("tick"), py::arg("now_ns") = py::none(),
           "tick: dict of MarketTick fields (absent or None = NaN). now_ns defaults to the tick's ts_ns.")
      .def("on_fill", &PyAlgo::fill, py::arg("instrument"), py::arg("qty"), py::arg("px"),
           "qty is signed: + bought, - sold")
      .def("on_reject", &PyAlgo::reject, py::arg("instrument"),
           "the last order on this instrument was rejected or expired unfilled (nothing traded)")
      .def_property_readonly("family", [](const PyAlgo& a) { return std::string(a.info->id); })
      .def_property_readonly("params", [](const PyAlgo& a) { return params_dict(*a.info, a.params); });

  m.def(
      "replay",
      [](const std::string& family, const py::dict& params, const py::dict& position, const py::dict& ticks,
         std::optional<py::dict> fees, const std::string& direction) {
        const FamilyInfo& f = family_or_throw(family);
        const Params p = params_from(f, params);
        const bool flip = flip_for(f, direction);
        const Position pos = oriented(position_from(position), flip);
        const std::vector<MarketTick> v = prepared_ticks(ticks, flip);
        const FeeModel fm = fees_from(fees);
        ReplayStats s;
        {
          py::gil_scoped_release nogil;
          s = replay(family, p, pos, v, fm);
        }
        py::dict d = stats_dict(s);
        d["params"] = params_dict(f, p);
        return d;
      },
      py::arg("family"), py::arg("params"), py::arg("position"), py::arg("ticks"), py::arg("fees") = py::none(),
      py::arg("direction") = "down_on_yes");

  m.def(
      "replay_grid",
      [](const std::string& family, const py::dict& position, const py::dict& ticks, std::optional<py::dict> fees,
         const std::string& direction) {
        const FamilyInfo& f = family_or_throw(family);
        const bool flip = flip_for(f, direction);
        const Position pos = oriented(position_from(position), flip);
        const std::vector<MarketTick> v = prepared_ticks(ticks, flip);
        const FeeModel fm = fees_from(fees);
        std::vector<ReplayStats> res;
        {
          py::gil_scoped_release nogil;
          res = replay_grid(family, pos, v, fm);
        }
        py::list out;
        for (const auto& s : res) {
          py::dict d = stats_dict(s);
          d["preset_index"] = s.preset_index;
          d["params"] = params_dict(f, s.params);
          out.append(d);
        }
        return out;
      },
      py::arg("family"), py::arg("position"), py::arg("ticks"), py::arg("fees") = py::none(),
      py::arg("direction") = "down_on_yes");

  py::class_<PyLadderPair>(m, "LadderPair")
      .def(py::init<const py::dict&>(), py::arg("params") = py::dict())
      .def("on_tick", &PyLadderPair::tick, py::arg("tick"), py::arg("now_ns") = py::none(),
           "tick: dict of LadderTick fields (absent or None = missing; nested None = missing). now_ns defaults to ts_ns.")
      .def("on_fill", [](PyLadderPair& a, const std::string& leg, double qty, double px) {
             a.algo.on_fill(leg_from(leg), qty, px);
           }, py::arg("leg"), py::arg("qty"), py::arg("px"), "leg: 'rich' | 'cheap'; qty: absolute quantity filled")
      .def("on_reject", [](PyLadderPair& a, const std::string& leg) { a.algo.on_reject(leg_from(leg)); },
           py::arg("leg"), "the leg's remaining quantity is dead (rejected, expired or cancelled)")
      .def_property_readonly("held", [](const PyLadderPair& a) { return a.algo.held; })
      .def_property_readonly("capital_locked", [](const PyLadderPair& a) { return a.algo.capital.locked; })
      .def_property_readonly("leg_risk_flagged", [](const PyLadderPair& a) { return a.algo.flagged; })
      .def_property_readonly("params", [](const PyLadderPair& a) { return micro_params_dict(*a.info, a.params); });

  py::class_<PyTouchTicket>(m, "TouchTicketReference")
      .def(py::init<const py::dict&>(), py::arg("params") = py::dict())
      .def("on_tick", &PyTouchTicket::tick, py::arg("tick"), py::arg("now_ns") = py::none(),
           "tick: dict of TicketTick fields. validated must be True for a live order; False or None gives proposals.")
      .def("on_fill", [](PyTouchTicket& a, double qty, double px) { a.algo.on_fill(qty, px); }, py::arg("qty"),
           py::arg("px"), "qty: absolute quantity sold")
      .def_property_readonly("sold", [](const PyTouchTicket& a) { return a.algo.sold; })
      .def_property_readonly("params", [](const PyTouchTicket& a) { return micro_params_dict(*a.info, a.params); });

  m.def(
      "replay_ladder",
      [](const py::dict& params, const py::dict& rows) {
        const MicroFamilyInfo& f = micro_or_throw("ladder_pair");
        const Params p = micro_params_from(f, params);
        const std::vector<LadderRow> v = ladder_rows_from(rows);
        LadderReplayStats s;
        {
          py::gil_scoped_release nogil;
          s = replay_ladder(p, v);
        }
        py::dict d;
        d["n_rows"] = s.n_rows;
        d["n_orders"] = s.n_orders;
        d["n_trades"] = s.n_trades;
        d["n_leg_rejects"] = s.n_leg_rejects;
        d["n_leg_risk"] = s.n_leg_risk;
        d["mean_pnl_points"] = nan_none(s.mean_pnl_points);
        d["total_pnl_usd"] = s.total_pnl_usd;
        d["total_capital_usd"] = s.total_capital_usd;
        d["min_pnl_minus_edge"] = nan_none(s.min_pnl_minus_edge);
        d["p50_ns"] = s.p50_ns;
        d["p99_ns"] = s.p99_ns;
        d["params"] = micro_params_dict(f, p);
        py::list trades;
        for (const auto& t : s.trades) {
          py::dict td;
          td["row"] = t.row;
          td["pair"] = t.pair;
          td["event"] = t.event;
          td["t_entry_ns"] = t.t_entry_ns;
          td["qty"] = t.qty;
          td["px_rich"] = t.px_rich;
          td["px_cheap"] = t.px_cheap;
          td["fee_rich"] = t.fee_rich;
          td["fee_cheap"] = t.fee_cheap;
          td["edge_locked"] = t.edge_locked;
          td["payoff"] = t.payoff;
          td["settled"] = t.settled;
          td["pnl_points"] = t.pnl_points;
          td["pnl_usd"] = t.pnl_usd;
          td["capital_usd"] = t.capital_usd;
          trades.append(td);
        }
        d["trades"] = trades;
        return d;
      },
      py::arg("params"), py::arg("rows"),
      "rows: dict of equal-length columns (now_ns, bid_rich, bid_rich_qty, ask_cheap, ask_cheap_qty, fee_rate_rich, "
      "fee_rate_cheap, tick, ts_rich_ns, ts_cheap_ns, nested, pair, event, result_rich, result_cheap). Fills only at "
      "the quoted bid/ask up to the quoted size.");

  m.def(
      "replay_tickets",
      [](const py::dict& params, const py::dict& rows) {
        const MicroFamilyInfo& f = micro_or_throw("touch_ticket_reference");
        const Params p = micro_params_from(f, params);
        const std::vector<TicketRow> v = ticket_rows_from(rows);
        TicketReplayStats s;
        {
          py::gil_scoped_release nogil;
          s = replay_tickets(p, v);
        }
        py::dict d;
        d["n_rows"] = s.n_rows;
        d["n_proposals"] = s.n_proposals;
        d["n_orders"] = s.n_orders;
        d["n_fills"] = s.n_fills;
        d["p50_ns"] = s.p50_ns;
        d["p99_ns"] = s.p99_ns;
        d["params"] = micro_params_dict(f, p);
        py::list decs;
        for (const auto& x : s.decisions) {
          py::dict dd;
          dd["row"] = x.row;
          dd["ticket"] = x.ticket;
          dd["action"] = micro_action_name(x.action);
          dd["qty"] = x.qty;
          dd["px"] = nan_none(x.px);
          dd["signal"] = nan_none(x.signal);
          dd["reason"] = reason_name(x.reason);
          dd["filled"] = x.filled;
          dd["pnl_points"] = nan_none(x.pnl_points);
          decs.append(dd);
        }
        d["decisions"] = decs;
        return d;
      },
      py::arg("params"), py::arg("rows"),
      "rows: dict of equal-length columns (now_ns, ts_ns, bid, bid_qty, ask, ref_lower, ref_central, validated, ticket, "
      "underlying, event, outcome). With validated False or None every decision is a proposal.");
}
