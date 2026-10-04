#include <pybind11/pybind11.h>

#include "hedgecore/stale_quote.hpp"

namespace py = pybind11;
using namespace hedgecore;

PYBIND11_MODULE(hedgecore_stale, m) {
  m.doc() = "Stale-quote detector (hedgecore/stale_quote.hpp)";
  m.def(
      "decide",
      [](double bid, double bid_size, double ask, double ask_size, double p_ref, double tau, double fee_rate,
         double fee_exp, bool fees_enabled) {
        StaleQuoteParams p;
        p.tau = tau;
        p.fee_rate = fee_rate;
        p.fee_exp = fee_exp;
        p.fees_enabled = fees_enabled;
        const StaleQuoteDecision d = stale_quote(bid, bid_size, ask, ask_size, p_ref, p);
        return py::make_tuple(static_cast<int>(d.side), d.edge_pt, d.net_edge_pt, d.price, d.size);
      },
      py::arg("bid"), py::arg("bid_size"), py::arg("ask"), py::arg("ask_size"), py::arg("p_ref"), py::arg("tau") = 0.05,
      py::arg("fee_rate") = 0.04, py::arg("fee_exp") = 1.0, py::arg("fees_enabled") = true);
  m.def("fee", [](double px, double fee_rate, double fee_exp, bool fees_enabled) {
    StaleQuoteParams p;
    p.fee_rate = fee_rate;
    p.fee_exp = fee_exp;
    p.fees_enabled = fees_enabled;
    return poly_taker_fee(px, p);
  });
}
