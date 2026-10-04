#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "hedgecore/book_engine.hpp"

namespace hedgecore {

struct FeedFrame {
  int32_t conn = 0;
  int32_t n = 0;
  int32_t dec_off = 0;
  int64_t t_sock = 0;
  int64_t t_recv = 0;
  int64_t t_read = 0;
  int64_t t0 = 0;
  int64_t t0_mono = 0;
  std::string raw;
};

struct FeedEvent {
  int32_t conn = 0;
  int32_t kind = 0;
  double t = 0.0;
  std::string msg;
};

struct FeedBatch {
  std::vector<FeedFrame> frames;
  std::vector<BookDecision> decisions;
  std::vector<FeedEvent> events;
};

class WsFeed {
 public:
  WsFeed(BookEngine& engine, std::mutex& engine_mu, std::string host, int port, std::string path, bool tls,
         std::string ca_file, bool spin, int ping_sec, int warm_us = 0);
  ~WsFeed();
  WsFeed(const WsFeed&) = delete;
  WsFeed& operator=(const WsFeed&) = delete;

  void start(std::vector<std::string> subscriptions);
  void stop();
  bool running() const noexcept;
  void drain(FeedBatch& out);
  int64_t frames() const noexcept;
  int64_t bad_frames() const noexcept;
  struct Conn;

 private:
  void run();
  bool open(Conn& c);
  void close(Conn& c, const std::string& why);
  bool send_text(Conn& c, const char* p, std::size_t n, int opcode);
  bool pump(Conn& c);
  void on_message(Conn& c, const char* p, std::size_t n, int64_t t_sock, int64_t t_recv, int64_t t_read);
  void event(int conn, int kind, const std::string& msg);

  BookEngine& eng_;
  std::mutex& eng_mu_;
  std::string host_, path_, ca_file_;
  int port_;
  bool tls_, spin_;
  int ping_sec_;
  int64_t warm_ns_;
  std::string warm_frame_;
  int64_t warm_epoch_ = -1;
  int64_t last_work_ = 0;
  void* ctx_ = nullptr;
  std::vector<std::unique_ptr<Conn>> conns_;
  std::thread th_;
  std::atomic<bool> stop_{false};
  std::atomic<bool> running_{false};
  std::atomic<int64_t> frames_{0};
  std::atomic<int64_t> bad_{0};
  std::mutex q_mu_;
  FeedBatch q_;
};

}
