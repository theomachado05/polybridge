#include "hedgecore/ws_feed.hpp"

#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <utility>

#include <openssl/err.h>
#include <openssl/ssl.h>
#ifdef __APPLE__
#include <pthread.h>
#include <sys/qos.h>
#endif

namespace hedgecore {

namespace {

int64_t wall_ns() noexcept {
  timespec ts;
  clock_gettime(CLOCK_REALTIME, &ts);
  return static_cast<int64_t>(ts.tv_sec) * 1000000000 + ts.tv_nsec;
}

double wall_s() noexcept { return static_cast<double>(wall_ns()) / 1e9; }

uint32_t rand32() noexcept {
#ifdef __APPLE__
  return arc4random();
#else
  return static_cast<uint32_t>(std::rand());
#endif
}

std::string b64(const unsigned char* p, std::size_t n) {
  static const char* t = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  std::string o;
  for (std::size_t i = 0; i < n; i += 3) {
    uint32_t v = static_cast<uint32_t>(p[i]) << 16;
    if (i + 1 < n) v |= static_cast<uint32_t>(p[i + 1]) << 8;
    if (i + 2 < n) v |= p[i + 2];
    o += t[(v >> 18) & 63];
    o += t[(v >> 12) & 63];
    o += i + 1 < n ? t[(v >> 6) & 63] : '=';
    o += i + 2 < n ? t[v & 63] : '=';
  }
  return o;
}

}

struct WsFeed::Conn {
  int id = 0;
  std::string sub;
  int fd = -1;
  SSL* ssl = nullptr;
  bool up = false;
  std::vector<char> buf = std::vector<char>(1 << 20);
  std::size_t beg = 0;
  std::size_t end = 0;
  std::string frag;
  int64_t next_ping = 0;
  int64_t retry_at = 0;
  double backoff = 1.0;
  bool down = false;
  int64_t t_recv = 0;
};

namespace {

long bio_cb(BIO* b, int oper, const char*, std::size_t, int, long, int ret, std::size_t* processed) {
  if (oper == (BIO_CB_READ | BIO_CB_RETURN) && ret > 0 && processed && *processed > 0)
    reinterpret_cast<WsFeed::Conn*>(BIO_get_callback_arg(b))->t_recv = BookEngine::mono_ns();
  return ret;
}

}

WsFeed::WsFeed(BookEngine& engine, std::mutex& engine_mu, std::string host, int port, std::string path, bool tls,
               std::string ca_file, bool spin, int ping_sec, int warm_us)
    : eng_(engine),
      eng_mu_(engine_mu),
      host_(std::move(host)),
      path_(std::move(path)),
      ca_file_(std::move(ca_file)),
      port_(port),
      tls_(tls),
      spin_(spin),
      ping_sec_(ping_sec),
      warm_ns_(static_cast<int64_t>(warm_us) * 1000) {
  if (tls_) {
    SSL_CTX* ctx = SSL_CTX_new(TLS_client_method());
    SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION);
    SSL_CTX_set_verify(ctx, SSL_VERIFY_PEER, nullptr);
    SSL_CTX_set_read_ahead(ctx, 1);
    if (ca_file_.empty() || SSL_CTX_load_verify_locations(ctx, ca_file_.c_str(), nullptr) != 1)
      SSL_CTX_set_default_verify_paths(ctx);
    ctx_ = ctx;
  }
}

WsFeed::~WsFeed() {
  stop();
  if (ctx_) SSL_CTX_free(static_cast<SSL_CTX*>(ctx_));
}

void WsFeed::start(std::vector<std::string> subscriptions) {
  stop();
  conns_.clear();
  for (std::size_t i = 0; i < subscriptions.size(); ++i) {
    auto c = std::make_unique<Conn>();
    c->id = static_cast<int>(i);
    c->sub = std::move(subscriptions[i]);
    conns_.push_back(std::move(c));
  }
  stop_ = false;
  running_ = true;
  th_ = std::thread([this] { run(); });
}

void WsFeed::stop() {
  stop_ = true;
  if (th_.joinable()) th_.join();
  for (auto& c : conns_)
    if (c->fd >= 0) close(*c, "stopped");
  running_ = false;
}

bool WsFeed::running() const noexcept { return running_; }
int64_t WsFeed::frames() const noexcept { return frames_; }
int64_t WsFeed::bad_frames() const noexcept { return bad_; }

void WsFeed::event(int conn, int kind, const std::string& msg) {
  std::lock_guard<std::mutex> g(q_mu_);
  q_.events.push_back(FeedEvent{conn, kind, wall_s(), msg});
}

void WsFeed::drain(FeedBatch& out) {
  out.frames.clear();
  out.decisions.clear();
  out.events.clear();
  std::lock_guard<std::mutex> g(q_mu_);
  std::swap(out.frames, q_.frames);
  std::swap(out.decisions, q_.decisions);
  std::swap(out.events, q_.events);
}

void WsFeed::close(Conn& c, const std::string& why) {
  if (c.ssl) {
    SSL_free(c.ssl);
    c.ssl = nullptr;
  }
  if (c.fd >= 0) {
    ::close(c.fd);
    c.fd = -1;
  }
  c.beg = c.end = 0;
  c.frag.clear();
  if (c.up) {
    c.up = false;
    c.down = true;
    event(c.id, 1, why);
  }
}

bool WsFeed::send_text(Conn& c, const char* p, std::size_t n, int opcode) {
  std::string f;
  f.reserve(n + 14);
  f += static_cast<char>(0x80 | opcode);
  if (n < 126) {
    f += static_cast<char>(0x80 | n);
  } else if (n < 65536) {
    f += static_cast<char>(0x80 | 126);
    f += static_cast<char>((n >> 8) & 0xff);
    f += static_cast<char>(n & 0xff);
  } else {
    f += static_cast<char>(0x80 | 127);
    for (int i = 7; i >= 0; --i) f += static_cast<char>((static_cast<uint64_t>(n) >> (8 * i)) & 0xff);
  }
  const uint32_t k = rand32();
  const unsigned char mk[4] = {static_cast<unsigned char>(k >> 24), static_cast<unsigned char>(k >> 16),
                               static_cast<unsigned char>(k >> 8), static_cast<unsigned char>(k)};
  f.append(reinterpret_cast<const char*>(mk), 4);
  for (std::size_t i = 0; i < n; ++i) f += static_cast<char>(p[i] ^ mk[i & 3]);
  std::size_t off = 0;
  for (int tries = 0; off < f.size() && tries < 100000; ++tries) {
    if (c.ssl) {
      const int r = SSL_write(c.ssl, f.data() + off, static_cast<int>(f.size() - off));
      if (r > 0) {
        off += static_cast<std::size_t>(r);
        continue;
      }
      const int e = SSL_get_error(c.ssl, r);
      if (e != SSL_ERROR_WANT_WRITE && e != SSL_ERROR_WANT_READ) return false;
    } else {
      const ssize_t r = ::send(c.fd, f.data() + off, f.size() - off, 0);
      if (r > 0) {
        off += static_cast<std::size_t>(r);
        continue;
      }
      if (r < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return false;
    }
    pollfd pf{c.fd, POLLOUT, 0};
    ::poll(&pf, 1, 10);
  }
  return off == f.size();
}

bool WsFeed::open(Conn& c) {
  addrinfo hints{};
  hints.ai_family = AF_UNSPEC;
  hints.ai_socktype = SOCK_STREAM;
  addrinfo* res = nullptr;
  const std::string port = std::to_string(port_);
  if (getaddrinfo(host_.c_str(), port.c_str(), &hints, &res) != 0 || !res) {
    if (res) freeaddrinfo(res);
    return false;
  }
  int fd = -1;
  for (addrinfo* a = res; a; a = a->ai_next) {
    fd = ::socket(a->ai_family, a->ai_socktype, a->ai_protocol);
    if (fd < 0) continue;
    timeval tv{15, 0};
    setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
    setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv);
    if (::connect(fd, a->ai_addr, a->ai_addrlen) == 0) break;
    ::close(fd);
    fd = -1;
  }
  freeaddrinfo(res);
  if (fd < 0) return false;
  int one = 1;
  setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
#ifdef SO_NOSIGPIPE
  setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
#endif
  c.fd = fd;
  c.beg = c.end = 0;
  if (tls_) {
    c.ssl = SSL_new(static_cast<SSL_CTX*>(ctx_));
    SSL_set_fd(c.ssl, fd);
    BIO* rb = SSL_get_rbio(c.ssl);
    BIO_set_callback_arg(rb, reinterpret_cast<char*>(&c));
    BIO_set_callback_ex(rb, bio_cb);
    SSL_set_tlsext_host_name(c.ssl, host_.c_str());
    SSL_set1_host(c.ssl, host_.c_str());
    if (SSL_connect(c.ssl) != 1) {
      ERR_clear_error();
      close(c, "tls handshake failed");
      return false;
    }
  }
  unsigned char key[16];
  for (int i = 0; i < 16; i += 4) {
    const uint32_t r = rand32();
    std::memcpy(key + i, &r, 4);
  }
  const std::string hostport = (tls_ && port_ == 443) || (!tls_ && port_ == 80) ? host_ : host_ + ":" + port;
  const std::string req = "GET " + path_ + " HTTP/1.1\r\nHost: " + hostport +
                          "\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: " + b64(key, 16) +
                          "\r\nSec-WebSocket-Version: 13\r\nUser-Agent: hedgecore-ws/1\r\n\r\n";
  std::size_t off = 0;
  while (off < req.size()) {
    const int r = c.ssl ? SSL_write(c.ssl, req.data() + off, static_cast<int>(req.size() - off))
                        : static_cast<int>(::send(fd, req.data() + off, req.size() - off, 0));
    if (r <= 0) {
      close(c, "upgrade write failed");
      return false;
    }
    off += static_cast<std::size_t>(r);
  }
  std::size_t hdr_end = std::string::npos;
  while (hdr_end == std::string::npos) {
    if (c.end >= c.buf.size()) {
      close(c, "upgrade response too large");
      return false;
    }
    const int r = c.ssl ? SSL_read(c.ssl, c.buf.data() + c.end, static_cast<int>(c.buf.size() - c.end))
                        : static_cast<int>(::recv(fd, c.buf.data() + c.end, c.buf.size() - c.end, 0));
    if (r <= 0) {
      ERR_clear_error();
      close(c, "upgrade read failed");
      return false;
    }
    c.end += static_cast<std::size_t>(r);
    const std::string_view sv(c.buf.data(), c.end);
    hdr_end = sv.find("\r\n\r\n");
  }
  const std::string_view status(c.buf.data(), c.end);
  if (status.substr(0, 12) != "HTTP/1.1 101") {
    close(c, "upgrade refused: " + std::string(status.substr(0, status.find("\r\n"))));
    return false;
  }
  c.beg = hdr_end + 4;
  fcntl(fd, F_SETFL, fcntl(fd, F_GETFL, 0) | O_NONBLOCK);
  if (!send_text(c, c.sub.data(), c.sub.size(), 1)) {
    close(c, "subscribe write failed");
    return false;
  }
  c.up = true;
  c.down = false;
  c.backoff = 1.0;
  c.next_ping = BookEngine::mono_ns() + static_cast<int64_t>(ping_sec_) * 1000000000;
  event(c.id, 0, "connected");
  return true;
}

void WsFeed::on_message(Conn& c, const char* p, std::size_t n, int64_t t_sock, int64_t t_recv, int64_t t_read) {
  if (n == 4 && std::memcmp(p, "PONG", 4) == 0) return;
  const int64_t t0 = wall_ns();
  const int64_t t0m = BookEngine::mono_ns();
  std::lock_guard<std::mutex> ge(eng_mu_);
  const int k = eng_.process(p, n, t0, t0m);
  std::lock_guard<std::mutex> gq(q_mu_);
  FeedFrame f;
  f.conn = c.id;
  f.n = k;
  f.dec_off = static_cast<int32_t>(q_.decisions.size());
  f.t_sock = t_sock;
  f.t_recv = t_recv;
  f.t_read = t_read;
  f.t0 = t0;
  f.t0_mono = t0m;
  if (k > 0) {
    const BookDecision* d = eng_.decisions();
    q_.decisions.insert(q_.decisions.end(), d, d + k);
  } else if (k < 0) {
    ++bad_;
  }
  f.raw.assign(p, n);
  q_.frames.push_back(std::move(f));
  ++frames_;
  if (warm_ns_ > 0 && k >= 0) {
    warm_frame_.assign(p, n);
    warm_epoch_ = eng_.epoch();
  }
  last_work_ = BookEngine::mono_ns();
}

bool WsFeed::pump(Conn& c) {
  for (;;) {
    if (c.buf.size() - c.end < 65536) {
      if (c.beg > 0) {
        std::memmove(c.buf.data(), c.buf.data() + c.beg, c.end - c.beg);
        c.end -= c.beg;
        c.beg = 0;
      }
      if (c.buf.size() - c.end < 65536) c.buf.resize(c.buf.size() * 2);
    }
    const int64_t t_sock = BookEngine::mono_ns();
    int r;
    if (c.ssl) {
      r = SSL_read(c.ssl, c.buf.data() + c.end, static_cast<int>(c.buf.size() - c.end));
      if (r <= 0) {
        const int e = SSL_get_error(c.ssl, r);
        if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) return true;
        ERR_clear_error();
        close(c, e == SSL_ERROR_ZERO_RETURN ? "closed by server" : "tls read error");
        return false;
      }
    } else {
      const ssize_t s = ::recv(c.fd, c.buf.data() + c.end, c.buf.size() - c.end, 0);
      if (s <= 0) {
        if (s < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return true;
        close(c, s == 0 ? "closed by server" : "read error");
        return false;
      }
      r = static_cast<int>(s);
    }
    const int64_t t_read = BookEngine::mono_ns();
    const int64_t t_recv = c.ssl ? c.t_recv : t_read;
    c.end += static_cast<std::size_t>(r);
    for (;;) {
      const std::size_t avail = c.end - c.beg;
      if (avail < 2) break;
      const unsigned char* h = reinterpret_cast<const unsigned char*>(c.buf.data() + c.beg);
      const bool fin = (h[0] & 0x80) != 0;
      const int op = h[0] & 0x0f;
      const bool masked = (h[1] & 0x80) != 0;
      uint64_t len = h[1] & 0x7f;
      std::size_t hl = 2;
      if (len == 126) {
        if (avail < 4) break;
        len = (static_cast<uint64_t>(h[2]) << 8) | h[3];
        hl = 4;
      } else if (len == 127) {
        if (avail < 10) break;
        len = 0;
        for (int i = 0; i < 8; ++i) len = (len << 8) | h[2 + i];
        hl = 10;
      }
      unsigned char mk[4] = {0, 0, 0, 0};
      if (masked) {
        if (avail < hl + 4) break;
        std::memcpy(mk, h + hl, 4);
        hl += 4;
      }
      if (avail < hl + len) break;
      char* pl = c.buf.data() + c.beg + hl;
      const std::size_t n = static_cast<std::size_t>(len);
      if (masked)
        for (std::size_t i = 0; i < n; ++i) pl[i] = static_cast<char>(pl[i] ^ mk[i & 3]);
      c.beg += hl + n;
      if (op == 1 || op == 2 || op == 0) {
        if (fin && op != 0 && c.frag.empty()) {
          on_message(c, pl, n, t_sock, t_recv, t_read);
        } else {
          c.frag.append(pl, n);
          if (fin) {
            on_message(c, c.frag.data(), c.frag.size(), t_sock, t_recv, t_read);
            c.frag.clear();
          }
        }
      } else if (op == 9) {
        if (!send_text(c, pl, n, 10)) {
          close(c, "pong write failed");
          return false;
        }
      } else if (op == 8) {
        close(c, "closed by server");
        return false;
      }
    }
    if (c.beg == c.end) c.beg = c.end = 0;
  }
}

void WsFeed::run() {
#ifdef __APPLE__
  pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
#endif
  std::vector<pollfd> pfs;
  while (!stop_) {
    const int64_t now = BookEngine::mono_ns();
    for (auto& cp : conns_) {
      Conn& c = *cp;
      if (stop_) break;
      if (!c.up) {
        if (now < c.retry_at) continue;
        if (!open(c)) {
          if (!c.down) {
            c.down = true;
            event(c.id, 1, "connect failed");
          }
          c.retry_at = BookEngine::mono_ns() + static_cast<int64_t>(c.backoff * 1e9);
          c.backoff = c.backoff * 2 > 60.0 ? 60.0 : c.backoff * 2;
        }
        continue;
      }
      if (!pump(c)) {
        c.retry_at = BookEngine::mono_ns() + static_cast<int64_t>(c.backoff * 1e9);
        continue;
      }
      if (now >= c.next_ping) {
        c.next_ping = now + static_cast<int64_t>(ping_sec_) * 1000000000;
        if (!send_text(c, "PING", 4, 1)) close(c, "ping write failed");
      }
    }
    if (spin_ && warm_ns_ > 0 && !warm_frame_.empty() && BookEngine::mono_ns() - last_work_ >= warm_ns_) {
      std::lock_guard<std::mutex> ge(eng_mu_);
      if (eng_.epoch() == warm_epoch_)
        eng_.rerun(warm_frame_.data(), warm_frame_.size());
      else
        warm_frame_.clear();
      last_work_ = BookEngine::mono_ns();
    }
    if (!spin_) {
      pfs.clear();
      for (auto& cp : conns_)
        if (cp->up) pfs.push_back(pollfd{cp->fd, POLLIN, 0});
      if (pfs.empty())
        ::usleep(50000);
      else
        ::poll(pfs.data(), static_cast<nfds_t>(pfs.size()), 50);
    }
  }
}

}
