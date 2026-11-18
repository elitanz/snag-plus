#!/usr/bin/env python3
"""Run Snag+ locally with live AI checks, using a free Google Gemini key.

    python3 serve.py            # then open http://localhost:8790

The key is read on this computer and added here, server-side. It is never sent to the
browser and never stored in this folder, so it can't leak through GitHub.

Key file (first one found):
  1. the SNAG_GEMINI_KEY_FILE environment variable
  2. ~/Claude Code/secrets/gemini.key
Optional: ~/Claude Code/secrets/groq.key answers the text-only "Ask about this item"
questions first (fast, generous free tier, but its free models can't see photos), which
saves Gemini's smaller free allowance for photo checks.
"""
import argparse
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
SECRETS = Path.home() / "Claude Code" / "secrets"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Each free Gemini model has its own daily quota and its own busy spells, so walk down the
# list. Lite models go first: on the free tier they answer in seconds, while the full Flash
# models are often overloaded and can hang for 30s+ (measured 2026-11-18).
GEMINI_MODELS = (
    "gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-flash-lite-latest",
    "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest",
)
GROQ_MODELS = ("openai/gpt-oss-120b", "openai/gpt-oss-20b")
SKIP_TO_NEXT = {404, 429, 500, 502, 503, 504}   # not on this key / quota spent / busy
MAX_BODY = 12 * 1024 * 1024
MAX_IMAGES = 3
MAX_PROMPT = 20000
PER_MODEL_TIMEOUT = 20      # seconds before giving up on one model
TOTAL_DEADLINE = 80         # seconds for the whole chain, so the page never waits forever
# After a model fails, skip it for a while so the next check goes straight to one that works.
COOLDOWN = {429: 3600, 404: 86400}   # quota spent: 1 hour; not on this key: 1 day
DEFAULT_COOLDOWN = 120               # busy or slow: 2 minutes
_cooldown_until: Dict[str, float] = {}
_cooldown_lock = threading.Lock()


def cool_down(model: str, status: Optional[int]) -> None:
    with _cooldown_lock:
        _cooldown_until[model] = time.monotonic() + COOLDOWN.get(status or 0, DEFAULT_COOLDOWN)


def ready_models() -> List[str]:
    now = time.monotonic()
    with _cooldown_lock:
        ready = [m for m in GEMINI_MODELS if _cooldown_until.get(m, 0) <= now]
    return ready or list(GEMINI_MODELS)   # everything cooling down: try them all again


def read_key(env_name: str, default_file: Path) -> Optional[str]:
    path = Path(os.environ.get(env_name, "") or default_file)
    try:
        key = path.read_text().strip()
    except OSError:
        return None
    return key or None


class UpstreamError(Exception):
    def __init__(self, code: str, status: Optional[int] = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: float) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise UpstreamError("rate_limited" if e.code == 429 else "upstream", e.code)
    except (socket.timeout, TimeoutError):          # socket.timeout isn't TimeoutError before 3.10
        raise UpstreamError("timeout", 504)
    except (urllib.error.URLError, ConnectionError, ValueError):
        raise UpstreamError("network")


def gemini_text(resp: Dict[str, Any]) -> str:
    parts = (((resp.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    return "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


def ask_gemini(key: str, contents: List[Dict[str, Any]], want_json: bool) -> Tuple[str, str]:
    config: Dict[str, Any] = {"temperature": 0.4}
    if want_json:
        config["responseMimeType"] = "application/json"
    body = {"contents": contents, "generationConfig": config}
    deadline = time.monotonic() + TOTAL_DEADLINE
    last = UpstreamError("upstream")
    for model in ready_models():
        left = deadline - time.monotonic()
        if left < 5:
            break
        try:
            resp = post_json(GEMINI_URL.format(model=model), body, {"x-goog-api-key": key},
                             min(PER_MODEL_TIMEOUT, left))
        except UpstreamError as e:
            last = e
            if e.status in SKIP_TO_NEXT or e.code in ("network", "timeout"):
                cool_down(model, e.status)
                sys.stderr.write("  %s unavailable (%s), trying the next model\n" % (model, e.status))
                continue
            raise
        text = gemini_text(resp)
        if text:
            return text, model
        last = UpstreamError("empty")
    raise last


def ask_groq(key: str, messages: List[Dict[str, str]]) -> Tuple[str, str]:
    last = UpstreamError("upstream")
    for model in GROQ_MODELS:
        try:
            resp = post_json(GROQ_URL, {"model": model, "messages": messages, "temperature": 0.4},
                             {"Authorization": "Bearer " + key, "User-Agent": "snag-local/1.0"},
                             PER_MODEL_TIMEOUT)
        except UpstreamError as e:
            last = e
            continue
        text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
        if text:
            return text, model
    raise last


def parse_json_text(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def valid_b64(s: Any) -> bool:
    if not isinstance(s, str) or not s or len(s) > 4 * 1024 * 1024:
        return False
    head = s[:4096]
    try:
        base64.b64decode(head + "=" * (-len(head) % 4), validate=True)
        return True
    except ValueError:
        return False


class Handler(SimpleHTTPRequestHandler):
    server_version = "SnagLocal/1.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(HERE), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("  %s\n" % (fmt % args))

    def send_json(self, status: int, obj: Dict[str, Any]) -> None:
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/api/ai/status":
            return self.send_json(200, {"ok": bool(self.server.gemini_key), "provider": "gemini"})
        if path in ("/serve.py", "/README.md") or "/." in path:
            return self.send_error(404)
        return super().do_GET()

    def do_POST(self) -> None:
        if self.path.split("?")[0] != "/api/ai":
            return self.send_error(404)
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY:
            return self.send_json(413, {"ok": False, "code": "too_large"})
        try:
            body = json.loads(self.rfile.read(length).decode())
        except ValueError:
            return self.send_json(400, {"ok": False, "code": "bad_request"})
        if not self.server.gemini_key:
            return self.send_json(503, {"ok": False, "code": "no_key"})
        try:
            if body.get("kind") == "json":
                return self.handle_json(body)
            if body.get("kind") == "text":
                return self.handle_text(body)
            return self.send_json(400, {"ok": False, "code": "bad_request"})
        except UpstreamError as e:
            sys.stderr.write("  AI request failed: %s (%s)\n" % (e.code, e.status))
            # The browser did reach this server, so a dropped link to Google counts as "busy", not "network".
            code = "upstream" if e.code == "network" else e.code
            return self.send_json(429 if code == "rate_limited" else 502, {"ok": False, "code": code})

    def handle_json(self, body: Dict[str, Any]) -> None:
        prompt, images = body.get("prompt"), body.get("images") or []
        if not isinstance(prompt, str) or not prompt or len(prompt) > MAX_PROMPT:
            return self.send_json(400, {"ok": False, "code": "bad_request"})
        if not isinstance(images, list) or len(images) > MAX_IMAGES or not all(valid_b64(i) for i in images):
            return self.send_json(400, {"ok": False, "code": "bad_request"})
        parts = [{"text": prompt}] + [{"inlineData": {"mimeType": "image/jpeg", "data": i}} for i in images]
        text, model = ask_gemini(self.server.gemini_key, [{"role": "user", "parts": parts}], True)
        try:
            data = parse_json_text(text)
        except ValueError:
            raise UpstreamError("bad_json")
        n = len(images)
        sys.stderr.write("  checked an item with %s (%d photo%s)\n" % (model, n, "" if n == 1 else "s"))
        return self.send_json(200, {"ok": True, "json": data, "model": model})

    def handle_text(self, body: Dict[str, Any]) -> None:
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs or len(msgs) > 40:
            return self.send_json(400, {"ok": False, "code": "bad_request"})
        clean: List[Dict[str, str]] = []
        for m in msgs:
            role, content = m.get("role"), m.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str) or len(content) > MAX_PROMPT:
                return self.send_json(400, {"ok": False, "code": "bad_request"})
            clean.append({"role": role, "content": content})
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in clean]
        text = model = None
        if self.server.groq_key:
            try:
                text, model = ask_groq(self.server.groq_key, clean)
            except UpstreamError:
                pass
        if text is None:
            text, model = ask_gemini(self.server.gemini_key, contents, False)
        sys.stderr.write("  answered a question with %s\n" % model)
        return self.send_json(200, {"ok": True, "text": text, "model": model})


def main() -> None:
    ap = argparse.ArgumentParser(description="Run Snag+ with live AI checks.")
    ap.add_argument("--port", type=int, default=8790)
    args = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.gemini_key = read_key("SNAG_GEMINI_KEY_FILE", SECRETS / "gemini.key")
    server.groq_key = read_key("SNAG_GROQ_KEY_FILE", SECRETS / "groq.key")
    print("Snag+ is running at http://localhost:%d" % args.port)
    print("AI checks: " + ("ON (free Gemini)" if server.gemini_key
                           else "OFF - no Gemini key found, see the top of serve.py"))
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
