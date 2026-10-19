"""A local stand-in for a gateway: Manifest, model list, and the three inference protocols."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeGateway:
    def __init__(self, *, key: str | None = "sk-test-key", manifest: dict[str, Any] | None = None):
        self.key = key
        self.manifest = manifest
        self.etag = '"v1"'
        self.manifest_status = 200
        self.models_list: list[dict[str, Any]] | None = None
        self.requests: list[dict[str, Any]] = []
        self.reply_text = "OK"
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._make_handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ---- lifecycle
    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FakeGateway":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "FakeGateway":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def hits(self, method: str, path: str) -> list[dict[str, Any]]:
        return [r for r in self.requests if r["method"] == method and r["path"] == path]

    # ---- handler
    def _make_handler(self) -> type[BaseHTTPRequestHandler]:
        gw = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a: object) -> None:
                pass

            def _record(self) -> dict[str, Any]:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = raw.decode("utf-8", "replace")
                rec = {
                    "method": self.command,
                    "path": self.path.split("?")[0],
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                }
                gw.requests.append(rec)
                return rec

            def _authorised(self, rec: dict[str, Any]) -> bool:
                if gw.key is None:
                    return True
                h = rec["headers"]
                return h.get("authorization") == f"Bearer {gw.key}" or h.get("x-api-key") == gw.key

            def _send(self, status: int, obj: Any, extra: dict[str, str] | None = None) -> None:
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                rec = self._record()
                if not self._authorised(rec):
                    return self._send(401, {"error": "unauthorized"})
                if rec["path"] == "/manifest":
                    if gw.manifest_status != 200:
                        return self._send(gw.manifest_status, {"error": "x"})
                    if gw.manifest is None:
                        return self._send(404, {"error": "no manifest"})
                    if rec["headers"].get("if-none-match") == gw.etag:
                        self.send_response(304)
                        self.send_header("ETag", gw.etag)
                        self.end_headers()
                        return None
                    return self._send(200, gw.manifest, {"ETag": gw.etag})
                if rec["path"] == "/v1/models":
                    data = gw.models_list if gw.models_list is not None else []
                    return self._send(200, {"object": "list", "data": data})
                return self._send(404, {"error": "not found"})

            def do_POST(self) -> None:
                rec = self._record()
                if not self._authorised(rec):
                    return self._send(401, {"error": "unauthorized"})
                reply = gw.reply_text
                model = (
                    (rec["body"] or {}).get("model", "x") if isinstance(rec["body"], dict) else "x"
                )
                stream = bool(isinstance(rec["body"], dict) and rec["body"].get("stream"))
                path = rec["path"]
                if path.endswith("/chat/completions"):
                    return _chat(self, model, reply, stream)
                if path.endswith("/messages"):
                    return _anthropic(self, model, reply, stream)
                if path.endswith("/responses"):
                    return _responses(self, model, reply, stream)
                return self._send(404, {"error": "not found"})

        return H


def _sse(handler: BaseHTTPRequestHandler, events: list[tuple[str | None, Any]]) -> None:
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    for name, obj in events:
        payload = obj if isinstance(obj, str) else json.dumps(obj)
        line = (f"event: {name}\n" if name else "") + f"data: {payload}\n\n"
        handler.wfile.write(line.encode())
    handler.wfile.flush()


def _chat(h: BaseHTTPRequestHandler, model: str, text: str, stream: bool) -> None:
    usage = {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}
    if not stream:
        body = {
            "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                         "finish_reason": "stop"}],
            "usage": usage,
        }  # fmt: skip
        data = json.dumps(body).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return
    base = {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": model}
    _sse(h, [
        (None, {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}),
        (None, {**base, "choices": [{"index": 0, "delta": {"content": text}}]}),
        (None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage}),
        (None, "[DONE]"),
    ])  # fmt: skip


def _anthropic(h: BaseHTTPRequestHandler, model: str, text: str, stream: bool) -> None:
    msg = {"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": [],
           "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 0}}  # fmt: skip
    if not stream:
        full = {**msg, "content": [{"type": "text", "text": text}], "stop_reason": "end_turn",
                "usage": {"input_tokens": 5, "output_tokens": 2}}  # fmt: skip
        data = json.dumps(full).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return
    _sse(h, [
        ("message_start", {"type": "message_start", "message": msg}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn",
                                                              "stop_sequence": None},
                           "usage": {"output_tokens": 2}}),
        ("message_stop", {"type": "message_stop"}),
    ])  # fmt: skip


def _responses(h: BaseHTTPRequestHandler, model: str, text: str, stream: bool) -> None:
    item = {"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}]}  # fmt: skip
    resp = {"id": "resp_1", "object": "response", "created_at": 1, "status": "completed",
            "model": model, "output": [item], "parallel_tool_calls": True, "tool_choice": "auto",
            "tools": [], "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7,
                                   "input_tokens_details": {"cached_tokens": 0},
                                   "output_tokens_details": {"reasoning_tokens": 0}}}  # fmt: skip
    if not stream:
        data = json.dumps(resp).encode()
        h.send_response(200)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(data)))
        h.end_headers()
        h.wfile.write(data)
        return
    inprog = {**resp, "status": "in_progress", "output": []}
    _sse(h, [
        ("response.created", {"type": "response.created", "response": inprog}),
        ("response.in_progress", {"type": "response.in_progress", "response": inprog}),
        ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0,
                                        "item": {**item, "status": "in_progress", "content": []}}),
        ("response.content_part.added", {"type": "response.content_part.added", "item_id": "msg_1",
                                         "output_index": 0, "content_index": 0,
                                         "part": {"type": "output_text", "text": "", "annotations": []}}),
        ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_1",
                                        "output_index": 0, "content_index": 0, "delta": text}),
        ("response.output_text.done", {"type": "response.output_text.done", "item_id": "msg_1",
                                       "output_index": 0, "content_index": 0, "text": text}),
        ("response.content_part.done", {"type": "response.content_part.done", "item_id": "msg_1",
                                        "output_index": 0, "content_index": 0,
                                        "part": {"type": "output_text", "text": text, "annotations": []}}),
        ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
        ("response.completed", {"type": "response.completed", "response": resp}),
    ])  # fmt: skip
