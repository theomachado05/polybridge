#pragma once
// Parameter definitions shared by the hedge families. Single-value grids are fixed settings: settable per bridge,
// never multiplied into the preset count.
#include "hedgecore/params.hpp"

namespace hedgecore::hp {

constexpr ParamDef impact() {
  return param("impact", 0, 1, 0.03, {0.03},
               "expected fractional stock move if the adverse event resolves (from the impact model); prices the "
               "fee gate's benefit; 0 disables the fee gate");
}
constexpr ParamDef session() {
  return param("session", 0, 1, 0, {0.0}, "1 = trade only in US equity regular hours (live bridges)");
}
constexpr ParamDef wash() {
  return param("wash_guard", 0, 1, 0, {0.0}, "1 = block re-shorting within 30 days of a loss cover (wash sale)");
}
constexpr ParamDef band(double def = 10) {
  return param("band_shares", 0, 1e6, def, {10.0, 25.0, 50.0}, "no-trade band: trade only if |h* - h| >= band");
}
constexpr ParamDef sigma_k() {
  return param("sigma_k", 0, 10, 1, {0.0, 1.0, 2.0}, "trade only when |dp| >= k * EWMA sigma of dp (0 = off)");
}

}  // namespace hedgecore::hp
