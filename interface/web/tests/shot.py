#!/usr/bin/env python3
"""Render a visual test page and capture a screenshot.

Usage: python tests/visual/shot.py <page.html> <out.png> [width height]
"""
import functools
import http.server
import os
import socketserver
import sys
import threading

from playwright.sync_api import sync_playwright

WEB_ROOT = os.path.join(os.path.dirname(__file__), "..")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_ROOT, **kwargs)

    def log_message(self, format, *args):
        pass


def main():
    page = sys.argv[1]
    out = sys.argv[2]
    width = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
    height = int(sys.argv[4]) if len(sys.argv) > 4 else 800

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                ctx = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2)
                pg = ctx.new_page()
                pg.goto(f"http://127.0.0.1:{port}/{page}")
                pg.wait_for_timeout(600)
                pg.screenshot(path=out, full_page=False)
                browser.close()
        finally:
            httpd.shutdown()
    print(f"saved {out}")


if __name__ == "__main__":
    main()
