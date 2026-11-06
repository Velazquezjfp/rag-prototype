#!/usr/bin/env python3
"""Probe embedding models behind any OpenAI-compatible endpoint (Ollama /v1, LiteLLM, vLLM, TEI): vector size and the
input length at which the server stops reading (truncation or error). Standard library only.

    BASE_URL=http://<host>:11434/v1 API_KEY=<key> python3 probe_embedding.py mxbai-embed-large:latest embeddinggemma:latest

How the cut-off is found: embed a German filler text of n words twice, once with a different-topic tail appended. If
the two vectors are identical, the server never read the tail, so it stops before n words. A server that rejects long
input instead shows up as an error at that length."""

import json
import math
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("BASE_URL", "http://localhost:11434/v1").rstrip("/")
KEY = os.environ.get("API_KEY", "none")
OPEN = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # like the app: ignore http(s)_proxy
FILL = "Die Sicherheitsdienste prüfen jeden Morgen die Zertifikate aller Server im Rechenzentrum. "  # 12 words
TAIL = " Ganz anderes Thema: Kaffeemaschine entkalken, Wassertank leeren und den Filter wechseln."
STEPS = [48, 120, 240, 360, 480, 720, 960, 1440, 1920, 2880, 3840, 5760]  # words


def embed(model: str, texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": model, "input": texts}).encode()
    req = urllib.request.Request(f"{BASE}/embeddings", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
    with OPEN(req, timeout=300) as r:
        return [d["embedding"] for d in json.load(r)["data"]]


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def probe(model: str) -> None:
    print(f"\n== {model}")
    try:
        dim = len(embed(model, ["Test"])[0])
    except urllib.error.HTTPError as exc:
        print(f"   not usable: HTTP {exc.code} {exc.read()[:200]!r}")
        return
    print(f"   vector size: {dim}")
    for words in STEPS:
        text = FILL * (words // 12)
        try:
            plain, tailed = embed(model, [text, text + TAIL])
        except urllib.error.HTTPError as exc:
            print(f"   {words:5} words: HTTP {exc.code} → the server rejects input this long: {exc.read()[:160]!r}")
            return
        diff = 1 - cos(plain, tailed)
        if diff < 1e-6:
            print(f"   {words:5} words: tail ignored (1-cos = {diff:.1e}) → the server cuts the input before this length")
            return
        print(f"   {words:5} words: tail read (1-cos = {diff:.1e})")
    print(f"   read everything up to {STEPS[-1]} words")


if __name__ == "__main__":
    for m in sys.argv[1:] or sys.exit(__doc__):
        probe(m)
