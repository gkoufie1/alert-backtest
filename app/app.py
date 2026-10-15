"""Sample 'orders' service with Prometheus metrics and a chaos endpoint.

POST /chaos?latency_ms=800&error_rate=0.2&duration_s=300  -> inject a fault
POST /chaos/stop                                          -> end it early
"""
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

ROUTE = "/api/orders"
REQUESTS = Counter("http_requests_total", "HTTP requests", ["route", "code"])
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)

_chaos = {"latency_ms": 0.0, "error_rate": 0.0, "until": 0.0}
_lock = threading.Lock()


def current_fault():
    with _lock:
        if time.time() > _chaos["until"]:
            return 0.0, 0.0
        return _chaos["latency_ms"], _chaos["error_rate"]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/metrics":
            return self.reply(200, generate_latest(), CONTENT_TYPE_LATEST)
        if path == "/healthz":
            return self.reply(200, {"ok": True})
        if path == ROUTE:
            started = time.perf_counter()
            extra_ms, error_rate = current_fault()
            time.sleep(random.uniform(0.005, 0.03) + extra_ms / 1000)
            code = 500 if random.random() < error_rate else 200
            LATENCY.labels(ROUTE).observe(time.perf_counter() - started)
            REQUESTS.labels(ROUTE, str(code)).inc()
            return self.reply(code, {"ok": code == 200})
        return self.reply(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/chaos":
            q = parse_qs(url.query)
            with _lock:
                _chaos["latency_ms"] = float(q.get("latency_ms", ["0"])[0])
                _chaos["error_rate"] = float(q.get("error_rate", ["0"])[0])
                _chaos["until"] = time.time() + float(q.get("duration_s", ["300"])[0])
                state = dict(_chaos)
            return self.reply(200, state)
        if url.path == "/chaos/stop":
            with _lock:
                _chaos["until"] = 0.0
            return self.reply(200, {"stopped": True})
        return self.reply(404, {"error": "not found"})


if __name__ == "__main__":
    print("orders service listening on :8000", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
