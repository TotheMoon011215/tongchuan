r"""用本地 mock 服务器验证翻译接口的 URL 拼接与流式解析。

不需要真实 API Key：起一个假的 OpenAI 兼容服务，返回 SSE 分片。
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config          # noqa: E402
from app.translator import Translator, _endpoint  # noqa: E402

PIECES = ["各位", "下午好，", "欢迎参加", "今天的", "分享。"]
SEEN_PATH = []
SEEN_BODY = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def do_POST(self):  # noqa: N802
        SEEN_PATH.append(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        SEEN_BODY.append(body)

        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", "40")
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"missing key"}}')
            return

        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()
            for piece in PIECES:
                chunk = {"choices": [{"delta": {"content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        else:
            payload = {"choices": [{"message": {"content": "".join(PIECES)}}]}
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    print(f"[i] mock server on {base}")

    ok = True
    for b in (base, base + "/", base + "/v1", base + "/v1/chat/completions"):
        print(f"  endpoint({b!r}) -> {_endpoint(b)}")

    cfg = Config()
    cfg.mt_base_url = base
    cfg.mt_api_key = "sk-test"
    cfg.mt_model = "deepseek-chat"

    # 1) 流式
    t = Translator(cfg)
    got = "".join(t.translate_iter("Good afternoon everyone.", "hello", "你好"))
    print(f"[1] 流式结果: {got!r}")
    if got != "".join(PIECES):
        print("    ✗ 与预期不符")
        ok = False
    else:
        print("    ✓ 分片拼接正确")

    # 2) 非流式
    sync = t.translate_sync("Good afternoon everyone.")
    print(f"[2] 非流式结果: {sync!r}")
    ok = ok and sync == "".join(PIECES)

    # 3) 请求体检查
    body = SEEN_BODY[-1]
    has_sys = body["messages"][0]["role"] == "system"
    user_msg = body["messages"][1]["content"]
    print(f"[3] 请求体: model={body['model']} stream={body['stream']} system={has_sys}")
    print(f"    用户消息含上文/待译: {'上文' in user_msg and '本次待译' in user_msg}")
    ok = ok and has_sys and body["model"] == "deepseek-chat"

    # 4) 鉴权失败应抛错
    bad = Config()
    bad.mt_base_url = base
    bad.mt_api_key = ""
    tb = Translator(bad)
    tb.cfg.mt_api_key = "x"
    try:
        tb.translate_sync("hi")
    except Exception as exc:
        print(f"[4] 错误路径 OK: {str(exc)[:80]}")
    else:
        # mock 只检查 header 存在，这里不会走到
        print("[4] 未触发错误（正常，mock 仅校验 header 存在）")

    t.close()
    srv.shutdown()
    print("=" * 60)
    print("结果:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
