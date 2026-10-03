#include <pybind11/pybind11.h>
#include "hedgecore/engine.hpp"

namespace py = pybind11;
using namespace hedgecore;

PYBIND11_MODULE(hedgecore, m) {
  m.doc() = "PolyBridge hedgecore: the C++20 hedge algorithm for user-approved hedges";

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
}
