#include "hedgecore/book_engine.hpp"

#include <time.h>

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <limits>
#include <string>
#include <unordered_map>
#include <vector>

#include "simdjson.h"

namespace hedgecore {

namespace od = simdjson::ondemand;

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

struct Level {
  int64_t k;
  double sz;
};

struct Side {
  std::vector<Level> lv;
  bool bid = true;

  int64_t key(int64_t px) const noexcept { return bid ? px : -px; }
  int64_t px(const Level& l) const noexcept { return bid ? l.k : -l.k; }

  void set(int64_t px, double sz) {
    const int64_t k = key(px);
    std::size_t i = lv.size();
    while (i > 0 && lv[i - 1].k > k) --i;
    if (i > 0 && lv[i - 1].k == k) {
      lv[i - 1].sz = sz;
      return;
    }
    lv.insert(lv.begin() + static_cast<std::ptrdiff_t>(i), Level{k, sz});
  }

  void erase(int64_t px) {
    const int64_t k = key(px);
    std::size_t i = lv.size();
    while (i > 0 && lv[i - 1].k > k) --i;
    if (i > 0 && lv[i - 1].k == k) lv.erase(lv.begin() + static_cast<std::ptrdiff_t>(i - 1));
  }

  double depth() const noexcept {
    const int64_t lo = lv.back().k - BookEngine::kDepthBand;
    double s = 0.0;
    for (std::size_t i = lv.size(); i > 0 && lv[i - 1].k >= lo; --i) s += lv[i - 1].sz;
    return s;
  }
};

struct Slot {
  Side bids, asks;
  int market = 0;
  bool yes = true;
  bool active = true;
};

struct Market {
  double p = kNaN;
  bool fees = true;
};

struct SvHash {
  using is_transparent = void;
  std::size_t operator()(std::string_view s) const noexcept { return std::hash<std::string_view>{}(s); }
};

inline double px_to_double(int64_t px) noexcept {
  return static_cast<double>(px) / static_cast<double>(BookEngine::kPxScale);
}

bool parse_px(std::string_view s, int64_t& out) {
  int64_t ip = 0, fp = 0;
  int fd = 0;
  std::size_t i = 0;
  const std::size_t n = s.size();
  bool digit = false;
  while (i < n && s[i] >= '0' && s[i] <= '9') {
    ip = ip * 10 + (s[i] - '0');
    if (ip > 1000000000) return false;
    digit = true;
    ++i;
  }
  if (i < n && s[i] == '.') {
    ++i;
    while (i < n && s[i] >= '0' && s[i] <= '9') {
      if (fd < 8) {
        fp = fp * 10 + (s[i] - '0');
        ++fd;
      } else if (s[i] != '0') {
        return false;
      }
      digit = true;
      ++i;
    }
  }
  if (i != n || !digit) return false;
  while (fd < 8) {
    fp *= 10;
    ++fd;
  }
  out = ip * BookEngine::kPxScale + fp;
  return true;
}

bool px_from_double(double d, int64_t& out) {
  if (!std::isfinite(d) || std::fabs(d) > 1e9) return false;
  out = std::llround(d * static_cast<double>(BookEngine::kPxScale));
  return true;
}

bool px_from_string(std::string_view s, int64_t& out) {
  if (parse_px(s, out)) return true;
  char tmp[64];
  if (s.empty() || s.size() >= sizeof(tmp)) return false;
  std::memcpy(tmp, s.data(), s.size());
  tmp[s.size()] = '\0';
  char* end = nullptr;
  const double d = std::strtod(tmp, &end);
  if (end == tmp) return false;
  return px_from_double(d, out);
}

bool read_px(od::value v, int64_t& out) {
  od::json_type t;
  if (v.type().get(t)) return false;
  if (t == od::json_type::string) {
    std::string_view s;
    if (v.get_string().get(s)) return false;
    return px_from_string(s, out);
  }
  if (t == od::json_type::number) {
    double d;
    if (v.get_double().get(d)) return false;
    return px_from_double(d, out);
  }
  return false;
}

bool read_sz(od::value v, double& out) {
  od::json_type t;
  if (v.type().get(t)) return false;
  if (t == od::json_type::string) return !v.get_double_in_string().get(out);
  if (t == od::json_type::number) return !v.get_double().get(out);
  return false;
}

}

struct BookEngine::Impl {
  StaleQuoteParams base;
  od::parser parser;
  std::vector<char> buf;
  std::vector<Slot> slots;
  std::unordered_map<std::string, int, SvHash, std::equal_to<>> idx;
  std::vector<Market> markets;
  std::vector<BookDecision> dec;
  std::vector<int> touched;
  int n = 0;
  int64_t bad = 0, other = 0, t0 = 0, t0m = 0;

  int lookup(std::string_view a) const {
    auto it = idx.find(a);
    if (it == idx.end() || !slots[it->second].active) return -1;
    return it->second;
  }

  void ensure_market(int m) {
    if (m >= static_cast<int>(markets.size())) markets.resize(static_cast<std::size_t>(m) + 1);
  }

  void touch(int s) {
    for (int t : touched)
      if (t == s) return;
    touched.push_back(s);
  }

  void decide(int s, int kind, int64_t m1) {
    const Slot& sl = slots[static_cast<std::size_t>(s)];
    double bb = 0.0, bs = 0.0, ba = 0.0, as = 0.0, bd = 0.0, ad = 0.0;
    if (!sl.bids.lv.empty()) {
      bb = px_to_double(sl.bids.px(sl.bids.lv.back()));
      bs = sl.bids.lv.back().sz;
      bd = sl.bids.depth();
    }
    if (!sl.asks.lv.empty()) {
      ba = px_to_double(sl.asks.px(sl.asks.lv.back()));
      as = sl.asks.lv.back().sz;
      ad = sl.asks.depth();
    }
    double yb, ybs, ya, yas, ybd, yad;
    if (sl.yes) {
      yb = bb, ybs = bs, ya = ba, yas = as, ybd = bd, yad = ad;
    } else {
      yb = ba > 0 ? 1.0 - ba : 0.0;
      ybs = ba > 0 ? as : 0.0;
      ya = bb > 0 ? 1.0 - bb : 0.0;
      yas = bb > 0 ? bs : 0.0;
      ybd = ad, yad = bd;
    }
    const Market& m = markets[static_cast<std::size_t>(sl.market)];
    StaleQuoteParams p = base;
    p.fees_enabled = m.fees;
    const StaleQuoteDecision d = stale_quote(yb, ybs, ya, yas, m.p, p);
    const int64_t m2 = BookEngine::mono_ns();
    if (n == static_cast<int>(dec.size())) dec.resize(dec.size() * 2);
    BookDecision& r = dec[static_cast<std::size_t>(n++)];
    r.slot = s;
    r.kind = kind;
    r.side = static_cast<int32_t>(d.side);
    r.bid = yb;
    r.bid_size = ybs;
    r.ask = ya;
    r.ask_size = yas;
    r.bid_depth = ybd;
    r.ask_depth = yad;
    r.p_ref = m.p;
    r.edge_pt = d.edge_pt;
    r.net_edge_pt = d.net_edge_pt;
    r.price = d.price;
    r.size = d.size;
    r.t1 = t0 + (m1 - t0m);
    r.t2 = t0 + (m2 - t0m);
  }

  void levels(od::object& o, std::string_view name, Side& side) {
    od::value v;
    if (o.find_field_unordered(name).get(v)) return;
    od::json_type t;
    if (v.type().get(t) || t != od::json_type::array) return;
    for (auto lr : v.get_array()) {
      od::object lo = lr.get_object();
      int64_t px = 0;
      double sz = 0.0;
      bool hp = false, hs = false;
      for (auto fr : lo) {
        od::field f;
        if (auto e = std::move(fr).get(f)) throw simdjson::simdjson_error(e);
        const std::string_view k = f.escaped_key();
        if (k == "price")
          hp = read_px(f.value(), px);
        else if (k == "size")
          hs = read_sz(f.value(), sz);
      }
      if (!hp || !hs) throw simdjson::simdjson_error(simdjson::INCORRECT_TYPE);
      side.set(px, sz);
    }
  }

  void book(od::object& o) {
    std::string_view a;
    if (o.find_field_unordered("asset_id").get_string().get(a)) return;
    const int s = lookup(a);
    if (s < 0) return;
    Slot& sl = slots[static_cast<std::size_t>(s)];
    sl.bids.lv.clear();
    sl.asks.lv.clear();
    levels(o, "bids", sl.bids);
    levels(o, "asks", sl.asks);
    decide(s, 0, BookEngine::mono_ns());
  }

  void change(od::object c, bool override_asset, int ov) {
    std::string_view a, side;
    bool has_a = false, hp = false, hs = false;
    int64_t px = 0;
    double sz = 0.0;
    for (auto fr : c) {
      od::field f;
      if (auto e = std::move(fr).get(f)) throw simdjson::simdjson_error(e);
      const std::string_view k = f.escaped_key();
      if (k == "asset_id") {
        if (!override_asset) has_a = !f.value().get_string().get(a);
      } else if (k == "price") {
        hp = read_px(f.value(), px);
      } else if (k == "size") {
        hs = read_sz(f.value(), sz);
      } else if (k == "side") {
        if (f.value().get_string().get(side)) side = std::string_view();
      }
    }
    const int s = override_asset ? ov : (has_a ? lookup(a) : -1);
    if (s < 0) return;
    if (!hp || !hs) throw simdjson::simdjson_error(simdjson::INCORRECT_TYPE);
    Slot& sl = slots[static_cast<std::size_t>(s)];
    Side& sd = side == "BUY" ? sl.bids : sl.asks;
    if (sz > 0)
      sd.set(px, sz);
    else
      sd.erase(px);
    touch(s);
  }

  void price_change(od::object& o) {
    touched.clear();
    bool any = false;
    od::value v;
    od::json_type t;
    if (!o.find_field_unordered("price_changes").get(v) && !v.type().get(t) && t == od::json_type::array) {
      for (auto cr : v.get_array()) {
        any = true;
        od::value cv = cr.value();
        if (cv.type() == od::json_type::object) change(cv.get_object(), false, -1);
      }
    }
    if (!any) {
      std::string_view a;
      const int ov = o.find_field_unordered("asset_id").get_string().get(a) ? -1 : lookup(a);
      if (!o.find_field_unordered("changes").get(v) && !v.type().get(t) && t == od::json_type::array) {
        for (auto cr : v.get_array()) {
          od::value cv = cr.value();
          if (cv.type() == od::json_type::object) change(cv.get_object(), true, ov);
        }
      }
    }
    if (touched.empty()) return;
    const int64_t m1 = BookEngine::mono_ns();
    for (int s : touched) decide(s, 1, m1);
  }

  void event(od::object o) {
    std::string_view et;
    if (o.find_field_unordered("event_type").get_string().get(et)) {
      ++other;
      return;
    }
    if (et == "book")
      book(o);
    else if (et == "price_change")
      price_change(o);
    else
      ++other;
  }
};

BookEngine::BookEngine(double tau, double fee_rate, double fee_exp, std::size_t frame_cap) : im_(new Impl) {
  im_->base.tau = tau;
  im_->base.fee_rate = fee_rate;
  im_->base.fee_exp = fee_exp;
  im_->buf.resize(frame_cap + simdjson::SIMDJSON_PADDING);
  if (im_->parser.allocate(frame_cap)) throw std::bad_alloc();
  im_->dec.resize(4096);
  im_->touched.reserve(4096);
  im_->slots.reserve(4096);
  im_->markets.reserve(4096);
}

BookEngine::~BookEngine() = default;

int BookEngine::add_asset(std::string_view asset_id, int market, bool is_yes) {
  im_->ensure_market(market);
  auto it = im_->idx.find(asset_id);
  int s;
  if (it == im_->idx.end()) {
    s = static_cast<int>(im_->slots.size());
    im_->slots.emplace_back();
    Slot& sl = im_->slots.back();
    sl.asks.bid = false;
    sl.bids.lv.reserve(256);
    sl.asks.lv.reserve(256);
    im_->idx.emplace(std::string(asset_id), s);
  } else {
    s = it->second;
  }
  Slot& sl = im_->slots[static_cast<std::size_t>(s)];
  sl.market = market;
  sl.yes = is_yes;
  sl.active = true;
  return s;
}

bool BookEngine::remove_asset(std::string_view asset_id) {
  auto it = im_->idx.find(asset_id);
  if (it == im_->idx.end()) return false;
  Slot& sl = im_->slots[static_cast<std::size_t>(it->second)];
  sl.active = false;
  sl.bids.lv.clear();
  sl.asks.lv.clear();
  return true;
}

int BookEngine::slot_of(std::string_view asset_id) const { return im_->lookup(asset_id); }

void BookEngine::set_market(int market, double p_ref, bool fees_enabled) {
  im_->ensure_market(market);
  im_->markets[static_cast<std::size_t>(market)].p = p_ref;
  im_->markets[static_cast<std::size_t>(market)].fees = fees_enabled;
}

void BookEngine::set_p(int market, double p_ref) {
  im_->ensure_market(market);
  im_->markets[static_cast<std::size_t>(market)].p = p_ref;
}

int BookEngine::process(const char* data, std::size_t len, int64_t t0, int64_t t0_mono) {
  Impl& I = *im_;
  I.n = 0;
  I.t0 = t0;
  I.t0m = t0_mono;
  if (len + simdjson::SIMDJSON_PADDING > I.buf.size()) I.buf.resize(len + simdjson::SIMDJSON_PADDING);
  std::memcpy(I.buf.data(), data, len);
  try {
    od::document doc = I.parser.iterate(I.buf.data(), len, I.buf.size());
    const od::json_type t = doc.type();
    if (t == od::json_type::array) {
      for (auto er : doc.get_array()) {
        od::value ev = er.value();
        if (ev.type() == od::json_type::object) I.event(ev.get_object());
      }
    } else if (t == od::json_type::object) {
      I.event(doc.get_object());
    }
  } catch (const simdjson::simdjson_error&) {
    ++I.bad;
    I.n = 0;
    return -1;
  }
  return I.n;
}

const BookDecision* BookEngine::decisions() const noexcept { return im_->dec.data(); }
int BookEngine::n_decisions() const noexcept { return im_->n; }
int64_t BookEngine::bad_frames() const noexcept { return im_->bad; }
int64_t BookEngine::other_events() const noexcept { return im_->other; }

int BookEngine::book_levels(int slot, bool bids) const {
  if (slot < 0 || slot >= static_cast<int>(im_->slots.size())) return -1;
  const Slot& sl = im_->slots[static_cast<std::size_t>(slot)];
  return static_cast<int>((bids ? sl.bids : sl.asks).lv.size());
}

int64_t BookEngine::mono_ns() noexcept {
#ifdef __APPLE__
  return static_cast<int64_t>(clock_gettime_nsec_np(CLOCK_UPTIME_RAW));
#else
  timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return static_cast<int64_t>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
#endif
}

}
