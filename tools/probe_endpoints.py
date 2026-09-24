# -*- coding: utf-8 -*-
"""外网/本地模型端点可达性核查（用与后端同一套 urllib 栈）。"""
import json
import urllib.error
import urllib.request


def hit(url, timeout=8, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(400).decode("utf-8", "replace")
            return r.status, body
    except urllib.error.HTTPError as e:
        return e.code, (e.read(200).decode("utf-8", "replace") if e.fp else "")
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


print("== 外网（Python urllib）==")
for url in ("https://api.openai.com/v1/models",
            "https://api.deepseek.com/v1/models",
            "https://dashscope.aliyuncs.com/compatible-mode/v1/models"):
    st, body = hit(url)
    print(f"  {url}\n    -> status={st} body={body[:110]!r}")

print("\n== 本机候选端点 ==")
for url in ("http://127.0.0.1:5000/",
            "http://127.0.0.1:5000/v1/models",
            "http://127.0.0.1:11434/api/tags",
            "http://127.0.0.1:1234/v1/models"):
    st, body = hit(url, timeout=4)
    print(f"  {url}\n    -> status={st} body={body[:160]!r}")
