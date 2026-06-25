import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

if len(sys.argv) != 3:
    print("Usage: python server.py <port> <html_file>")
    sys.exit(1)

PORT = int(sys.argv[1])
HTML_FILE = sys.argv[2]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            with open(HTML_FILE, "rb") as f:
                content = f.read()

            # 503 (not 200): the construction site is a maintenance page,
            # so the service must signal "temporarily unavailable" to
            # browsers, crawlers and monitoring instead of pretending OK.
            self.send_response(503)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Retry-After", "30")
            self.end_headers()
            self.wfile.write(content)

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error")

    # disable logging noise
    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Serving {HTML_FILE} on port {PORT}")
    server.serve_forever()
