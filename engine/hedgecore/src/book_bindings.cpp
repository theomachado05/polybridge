#include <pybind11/pybind11.h>

#include <pybind11/stl.h>

#include <atomic>
#include <mutex>
#include <string>
#include <vector>
#include <thread>
#ifdef __APPLE__
#include <pthread.h>
#include <sys/qos.h>
#endif

#include "hedgecore/book_engine.hpp"
#include "hedgecore/ws_feed.hpp"

namespace py = pybind11;
using namespace hedgecore;

namespace {

std::atomic<bool> g_warm{false};
std::atomic<int> g_gen{0};

struct LockedEngine : BookEngine {
  LockedEngine(double tau, double fee_rate, double fee_exp) : BookEngine(tau, fee_rate, fee_exp) {}
  std::mutex mu;
};

using Guard = std::lock_guard<std::mutex>;

py::tuple dec_tuple(const BookDecision& r) {
  return py::make_tuple(r.slot, r.kind, r.side, r.bid, r.bid_size, r.ask, r.ask_size, r.bid_depth, r.ask_depth, r.p_ref,
                        r.edge_pt, r.net_edge_pt, r.price, r.size, r.t1, r.t2);
}

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
  py::class_<LockedEngine>(m, "BookEngine")
      .def(py::init<double, double, double>(), py::arg("tau"), py::arg("fee_rate") = 0.04, py::arg("fee_exp") = 1.0)
      .def("add_asset",
           [](LockedEngine& e, std::string_view a, int market, bool is_yes) {
             Guard g(e.mu);
             return e.add_asset(a, market, is_yes);
           })
      .def("remove_asset",
           [](LockedEngine& e, std::string_view a) {
             Guard g(e.mu);
             return e.remove_asset(a);
           })
      .def("slot_of",
           [](LockedEngine& e, std::string_view a) {
             Guard g(e.mu);
             return e.slot_of(a);
           })
      .def("set_market",
           [](LockedEngine& e, int market, double p_ref, bool fees) {
             Guard g(e.mu);
             e.set_market(market, p_ref, fees);
           })
      .def("set_p",
           [](LockedEngine& e, int market, double p_ref) {
             Guard g(e.mu);
             e.set_p(market, p_ref);
           })
      .def("rerun",
           [](LockedEngine& e, py::bytes frame) {
             char* data;
             Py_ssize_t len;
             PyBytes_AsStringAndSize(frame.ptr(), &data, &len);
             Guard g(e.mu);
             return e.rerun(data, static_cast<std::size_t>(len));
           })
      .def_property_readonly("epoch", [](LockedEngine& e) { Guard g(e.mu); return e.epoch(); })
      .def("book_levels",
           [](LockedEngine& e, int slot, bool bids) {
             Guard g(e.mu);
             return e.book_levels(slot, bids);
           })
      .def(
          "process",
          [](LockedEngine& e, py::handle frame, int64_t t0, int64_t t0_mono) {
            char* data;
            Py_ssize_t len;
            if (PyBytes_AsStringAndSize(frame.ptr(), &data, &len) != 0) throw py::error_already_set();
            Guard g(e.mu);
            return e.process(data, static_cast<std::size_t>(len), t0, t0_mono);
          },
          py::arg("frame"), py::arg("t0"), py::arg("t0_mono"))
      .def("decisions",
           [](LockedEngine& e) {
             Guard g(e.mu);
             const int n = e.n_decisions();
             const BookDecision* d = e.decisions();
             py::list out(n);
             for (int i = 0; i < n; ++i) out[i] = dec_tuple(d[i]);
             return out;
           })
      .def_property_readonly("bad_frames", [](LockedEngine& e) { Guard g(e.mu); return e.bad_frames(); })
      .def_property_readonly("other_events", [](LockedEngine& e) { Guard g(e.mu); return e.other_events(); });
  py::class_<WsFeed>(m, "WsFeed")
      .def(py::init([](LockedEngine& e, std::string host, int port, std::string path, bool tls, std::string ca_file,
                       bool spin, int ping_sec, int warm_us) {
             return new WsFeed(e, e.mu, std::move(host), port, std::move(path), tls, std::move(ca_file), spin, ping_sec,
                               warm_us);
           }),
           py::arg("engine"), py::arg("host"), py::arg("port") = 443, py::arg("path") = "/", py::arg("tls") = true,
           py::arg("ca_file") = "", py::arg("spin") = false, py::arg("ping_sec") = 10, py::arg("warm_us") = 0,
           py::keep_alive<1, 2>())
      .def("start", &WsFeed::start, py::arg("subscriptions"), py::call_guard<py::gil_scoped_release>())
      .def("stop", &WsFeed::stop, py::call_guard<py::gil_scoped_release>())
      .def_property_readonly("running", &WsFeed::running)
      .def_property_readonly("frames", &WsFeed::frames)
      .def_property_readonly("bad_frames", &WsFeed::bad_frames)
      .def("drain", [](WsFeed& f) {
        FeedBatch b;
        f.drain(b);
        py::list frames(b.frames.size());
        for (std::size_t i = 0; i < b.frames.size(); ++i) {
          const FeedFrame& x = b.frames[i];
          const int k = x.n > 0 ? x.n : 0;
          py::list ds(k);
          for (int j = 0; j < k; ++j) ds[j] = dec_tuple(b.decisions[static_cast<std::size_t>(x.dec_off + j)]);
          frames[i] = py::make_tuple(x.conn, x.n, x.t0 - (x.t0_mono - x.t_sock), x.t0 - (x.t0_mono - x.t_recv),
                                     x.t0 - (x.t0_mono - x.t_read), x.t0, py::bytes(x.raw), ds);
        }
        py::list events(b.events.size());
        for (std::size_t i = 0; i < b.events.size(); ++i)
          events[i] = py::make_tuple(b.events[i].conn, b.events[i].kind, b.events[i].t, b.events[i].msg);
        return py::make_tuple(frames, events);
      });
  m.def("mono_ns", &BookEngine::mono_ns);
  m.def("set_interactive_qos", &set_interactive_qos);
  m.def("keep_warm", &keep_warm, py::arg("on"));
}
