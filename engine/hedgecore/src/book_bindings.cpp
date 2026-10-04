#include <pybind11/pybind11.h>

#include <atomic>
#include <thread>
#ifdef __APPLE__
#include <pthread.h>
#include <sys/qos.h>
#endif

#include "hedgecore/book_engine.hpp"

namespace py = pybind11;
using namespace hedgecore;

namespace {

std::atomic<bool> g_warm{false};
std::atomic<int> g_gen{0};

bool set_interactive_qos() {
#ifdef __APPLE__
  return pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0) == 0;
#else
  return false;
#endif
}

void keep_warm(bool on) {
  if (on == g_warm.exchange(on) || !on) return;
  const int gen = ++g_gen;
  std::thread([gen] {
    set_interactive_qos();
    while (g_warm.load(std::memory_order_relaxed) && g_gen.load(std::memory_order_relaxed) == gen) {
    }
  }).detach();
}

}

PYBIND11_MODULE(hedgecore_book, m) {
  m.doc() = "Frame-to-decision engine (hedgecore/book_engine.hpp): simdjson parse, per-token books, stale-quote rule";
  py::class_<BookEngine>(m, "BookEngine")
      .def(py::init<double, double, double>(), py::arg("tau"), py::arg("fee_rate") = 0.04, py::arg("fee_exp") = 1.0)
      .def("add_asset", [](BookEngine& e, std::string_view a, int market, bool is_yes) { return e.add_asset(a, market, is_yes); })
      .def("remove_asset", [](BookEngine& e, std::string_view a) { return e.remove_asset(a); })
      .def("slot_of", [](const BookEngine& e, std::string_view a) { return e.slot_of(a); })
      .def("set_market", &BookEngine::set_market)
      .def("set_p", &BookEngine::set_p)
      .def("book_levels", &BookEngine::book_levels)
      .def(
          "process",
          [](BookEngine& e, py::handle frame, int64_t t0, int64_t t0_mono) {
            char* data;
            Py_ssize_t len;
            if (PyBytes_AsStringAndSize(frame.ptr(), &data, &len) != 0) throw py::error_already_set();
            return e.process(data, static_cast<std::size_t>(len), t0, t0_mono);
          },
          py::arg("frame"), py::arg("t0"), py::arg("t0_mono"))
      .def("decisions",
           [](const BookEngine& e) {
             const int n = e.n_decisions();
             const BookDecision* d = e.decisions();
             py::list out(n);
             for (int i = 0; i < n; ++i) {
               const BookDecision& r = d[i];
               out[i] = py::make_tuple(r.slot, r.kind, r.side, r.bid, r.bid_size, r.ask, r.ask_size, r.bid_depth,
                                       r.ask_depth, r.p_ref, r.edge_pt, r.net_edge_pt, r.price, r.size, r.t1, r.t2);
             }
             return out;
           })
      .def_property_readonly("bad_frames", &BookEngine::bad_frames)
      .def_property_readonly("other_events", &BookEngine::other_events);
  m.def("mono_ns", &BookEngine::mono_ns);
  m.def("set_interactive_qos", &set_interactive_qos);
  m.def("keep_warm", &keep_warm, py::arg("on"));
}
