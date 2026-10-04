#pragma once
#include <array>
#include <cmath>
#include <cstddef>
#include <string_view>
#include "hedgecore/market.hpp"

namespace hedgecore {

inline constexpr int kMaxGrid = 6;

struct ParamDef {
  const char* name = "";
  double min = 0, max = 0, def = 0;
  std::array<double, kMaxGrid> grid{};
  int n_grid = 0;
  const char* help = "";
};

template <std::size_t N>
constexpr ParamDef param(const char* name, double lo, double hi, double def, const double (&g)[N], const char* help) {
  static_assert(N >= 1 && N <= kMaxGrid, "grid must have 1..6 values");
  ParamDef d;
  d.name = name;
  d.min = lo;
  d.max = hi;
  d.def = def;
  for (std::size_t i = 0; i < N; ++i) d.grid[i] = g[i];
  d.n_grid = static_cast<int>(N);
  d.help = help;
  return d;
}

struct ParamSpec {
  std::array<ParamDef, kMaxParams> defs{};
  int n = 0;

  constexpr ParamSpec() = default;
  template <typename... D>
  constexpr explicit ParamSpec(D... d) : defs{d...}, n(static_cast<int>(sizeof...(D))) {
    static_assert(sizeof...(D) <= kMaxParams);
  }

  constexpr std::size_t preset_count() const noexcept {
    std::size_t c = 1;
    for (int i = 0; i < n; ++i) c *= static_cast<std::size_t>(defs[i].n_grid);
    return c;
  }
  constexpr int tuned_count() const noexcept {
    int c = 0;
    for (int i = 0; i < n; ++i) c += defs[i].n_grid > 1;
    return c;
  }
  constexpr Params preset(std::size_t idx) const noexcept {
    Params p = defaults();
    for (int i = n - 1; i >= 0; --i) {
      const auto g = static_cast<std::size_t>(defs[i].n_grid);
      p.v[i] = defs[i].grid[idx % g];
      idx /= g;
    }
    return p;
  }
  constexpr Params defaults() const noexcept {
    Params p;
    for (int i = 0; i < n; ++i) p.v[i] = defs[i].def;
    return p;
  }
  constexpr int index_of(std::string_view name) const noexcept {
    for (int i = 0; i < n; ++i)
      if (name == defs[i].name) return i;
    return -1;
  }
  bool valid(const Params& p) const noexcept {
    for (int i = 0; i < n; ++i)
      if (!std::isfinite(p.v[i]) || p.v[i] < defs[i].min || p.v[i] > defs[i].max) return false;
    return true;
  }
};

}
