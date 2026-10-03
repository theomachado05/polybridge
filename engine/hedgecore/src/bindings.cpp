#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cmath>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "hedgecore/engine.hpp"
#include "hedgecore/library.hpp"
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

// The YES/NO flip is defined only for the hedge division: those families trade equity alone, so flipping the tick
// changes which outcome counts as adverse and nothing else. Prediction-market and option families name real
// contracts in their intents (pred_yes / pred_no) and compare against option-implied fields, so flipping their
// input would make them trade the wrong leg; for them direction must stay 'down_on_yes'.
bool flip_for(const FamilyInfo& f, const std::string& direction) {
  const bool flip = flip_from(direction);
  if (flip && std::string_view(f.division) != "hedge")
    throw py::value_error(std::string("direction='up_on_yes' applies only to hedge-division families; '") + f.id +
                          "' is division '" + f.division + "' (its intents name the real YES/NO contract)");
  return flip;
}

// Under the flip the position's YES and NO holdings swap too, so replay marks them on the flipped book.
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

// bid_px_0..4, bid_qty_0..4, ask_px_0..4, ask_qty_0..4
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

// ticks: dict of equal-length arrays named like the MarketTick fields; absent arrays mean NaN.
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
  d["turnover"] = s.turnover;
  d["p50_ns"] = s.p50_ns;
  d["p99_ns"] = s.p99_ns;
  return d;
}

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
  return out;
}

// Python-facing algo: owns the variant and applies the YES/NO flip for up_on_yes positions.
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

}  // namespace

PYBIND11_MODULE(hedgecore, m) {
  m.doc() = "PolyBridge hedgecore: the C++20 algo library (16 families) and the legacy Engine";

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

  // ---- v4 algo library ----
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
}
