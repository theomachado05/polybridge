#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string_view>

#include "hedgecore/stale_quote.hpp"

namespace hedgecore {

struct BookDecision {
  int32_t slot = -1;
  int32_t kind = 0;
  int32_t side = 0;
  double bid = 0.0;
  double bid_size = 0.0;
  double ask = 0.0;
  double ask_size = 0.0;
  double bid_depth = 0.0;
  double ask_depth = 0.0;
  double p_ref = 0.0;
  double edge_pt = 0.0;
  double net_edge_pt = 0.0;
  double price = 0.0;
  double size = 0.0;
  int64_t t1 = 0;
  int64_t t2 = 0;
};

class BookEngine {
 public:
  static constexpr int64_t kPxScale = 100000000;
  static constexpr int64_t kDepthBand = 2000000;

  BookEngine(double tau, double fee_rate, double fee_exp, std::size_t frame_cap = 1 << 22);
  ~BookEngine();
  BookEngine(const BookEngine&) = delete;
  BookEngine& operator=(const BookEngine&) = delete;

  int add_asset(std::string_view asset_id, int market, bool is_yes);
  bool remove_asset(std::string_view asset_id);
  int slot_of(std::string_view asset_id) const;
  void set_market(int market, double p_ref, bool fees_enabled);
  void set_p(int market, double p_ref);

  int process(const char* data, std::size_t len, int64_t t0, int64_t t0_mono);
  int rerun(const char* data, std::size_t len);
  int64_t epoch() const noexcept;
  const BookDecision* decisions() const noexcept;
  int n_decisions() const noexcept;
  int64_t bad_frames() const noexcept;
  int64_t other_events() const noexcept;
  int book_levels(int slot, bool bids) const;

  static int64_t mono_ns() noexcept;

 private:
  struct Impl;
  std::unique_ptr<Impl> im_;
};

}
