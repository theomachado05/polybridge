#pragma once
// Minimal RFC 4180 CSV reader for the research result files the micro-family tests replay (quoted fields may hold
// commas and doubled quotes). Test-only.
#include <algorithm>
#include <fstream>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace hctest {

struct Csv {
  std::vector<std::string> header;
  std::vector<std::vector<std::string>> rows;
  std::map<std::string, std::size_t> col;
  const std::string& at(std::size_t r, const std::string& name) const { return rows[r][col.at(name)]; }
};

inline std::vector<std::string> csv_split(const std::string& line) {
  std::vector<std::string> out;
  std::string cur;
  bool q = false;
  for (std::size_t i = 0; i < line.size(); ++i) {
    const char c = line[i];
    if (q) {
      if (c == '"' && i + 1 < line.size() && line[i + 1] == '"') { cur += '"'; ++i; }
      else if (c == '"') q = false;
      else cur += c;
    } else if (c == '"') q = true;
    else if (c == ',') { out.push_back(cur); cur.clear(); }
    else if (c != '\r') cur += c;
  }
  out.push_back(cur);
  return out;
}

inline Csv read_csv(const std::string& path) {
  Csv c;
  std::ifstream in(path);
  std::string line, rec;
  bool first = true;
  while (std::getline(in, line)) {
    rec += line;
    if (std::count(rec.begin(), rec.end(), '"') % 2) { rec += '\n'; continue; }  // a quoted newline
    auto f = csv_split(rec);
    rec.clear();
    if (first) {
      c.header = f;
      for (std::size_t i = 0; i < f.size(); ++i) c.col[f[i]] = i;
      first = false;
    } else if (!(f.size() == 1 && f[0].empty())) {
      c.rows.push_back(std::move(f));
    }
  }
  return c;
}

inline double to_d(const std::string& s) {
  if (s.empty() || s == "nan" || s == "NaN") return std::numeric_limits<double>::quiet_NaN();
  if (s == "True") return 1;
  if (s == "False") return 0;
  return std::stod(s);
}

}  // namespace hctest
