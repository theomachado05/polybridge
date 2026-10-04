// Prints the golden text of the 17 pre-existing families to stdout (see golden_render.hpp). Built by CI on the base
// commit and on the branch with identical flags; the two outputs must be byte-identical.
#include <cstdio>
#include "golden_render.hpp"

int main() {
  const std::string s = hcgolden::render();
  std::fwrite(s.data(), 1, s.size(), stdout);
  return 0;
}
