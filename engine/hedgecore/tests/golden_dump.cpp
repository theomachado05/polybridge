#include <cstdio>
#include "golden_render.hpp"

int main() {
  const std::string s = hcgolden::render();
  std::fwrite(s.data(), 1, s.size(), stdout);
  return 0;
}
