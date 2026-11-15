"""英译中翻译：调用 OpenAI 兼容的 Chat Completions 接口（默认 DeepSeek），流式返回。"""

from __future__ import annotations

import json
import time
from typing import Iterator

import httpx

SYSTEM_PROMPT = """你是一名顶级英中同声传译员，正在为一场实时英文演讲生成中文字幕。

必须遵守：
1. 只输出简体中文译文本身。不要输出英文原文、拼音、解释、序号、引号或“译文：”之类的前缀。
2. 用口语化的书面语，简洁自然，符合中文字幕的阅读习惯；不要生硬直译，不要书面腔过重。
3. 准确传达信息、逻辑和语气；数字、单位、人名、机构名、专业术语必须准确。
4. 输入可能是半句话或片段：只翻译给出的内容，不要补全、不要预测后文、不要重复已经译过的部分。
5. 如果给出了“上文”，只是用来理解指代、保持术语和语气一致，不要把上文再翻译一遍。
6. 遇到口头语、语气词、无意义重复，可以省略或合并，保证译文通顺。"""

USER_TMPL = """{glossary}【上文英文】{ctx_en}
【上文译文】{ctx_zh}
【本次待译】{text}

只输出【本次待译】这一段的中文译文。"""


def _endpoint(base: str) -> str:
    b = (base or "").strip().rstrip("/")
    if not b:
        b = "https://api.deepseek.com"
    if b.endswith("/chat/completions"):
        return b
    if b.endswith("/v1"):
        return b + "/chat/completions"
    return b + "/v1/chat/completions"


def _clean(text: str) -> str:
    t = text.strip()
    for prefix in ("译文：", "译文:", "翻译：", "翻译:", "中文：", "中文:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    return t


class Translator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.last_error = ""
        self._client: httpx.Client | None = None

    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.cfg.mt_enabled and self.cfg.api_key)

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.cfg.mt_timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            finally:
                self._client = None

    # ------------------------------------------------------------------
    def _payload(self, text: str, ctx_en: str, ctx_zh: str, stream: bool) -> dict:
        pairs = self.cfg.glossary_pairs()
        glossary = ""
        if pairs:
            lines = "\n".join(f"- {a} → {b}" for a, b in pairs)
            glossary = f"【术语表（必须遵守）】\n{lines}\n\n"
        user = USER_TMPL.format(
            glossary=glossary,
            ctx_en=(ctx_en or "（无）")[-600:],
            ctx_zh=(ctx_zh or "（无）")[-400:],
            text=text,
        )
        return {
            "model": self.cfg.mt_model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": stream,
            "temperature": float(self.cfg.mt_temperature),
            "max_tokens": 512,
        }

    # ------------------------------------------------------------------
    def translate_iter(
        self, text: str, ctx_en: str = "", ctx_zh: str = ""
    ) -> Iterator[str]:
        """流式产出中文增量片段。出错时抛出异常，由调用方处理。"""
        if not text.strip():
            return
        client = self._get_client()
        url = _endpoint(self.cfg.mt_base_url)
        payload = self._payload(text, ctx_en, ctx_zh, True)

        for attempt in (0, 1):
            try:
                with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = resp.read().decode("utf-8", "ignore")[:400]
                        raise RuntimeError(f"HTTP {resp.status_code}: {body}")
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            obj = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        if "error" in obj and obj["error"]:
                            raise RuntimeError(str(obj["error"])[:300])
                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        delta = (choices[0].get("delta") or {}).get("content")
                        if delta:
                            yield delta
                    return
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if attempt == 0:
                    time.sleep(0.4)
                    continue
                self.last_error = str(exc)
                raise

    # ------------------------------------------------------------------
    def translate_sync(self, text: str, ctx_en: str = "", ctx_zh: str = "") -> str:
        client = self._get_client()
        url = _endpoint(self.cfg.mt_base_url)
        payload = self._payload(text, ctx_en, ctx_zh, False)
        resp = client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        obj = resp.json()
        content = obj["choices"][0]["message"]["content"]
        return _clean(content)

    def test(self) -> str:
        return self.translate_sync(
            "Good afternoon everyone, thanks for joining today's session."
        )
