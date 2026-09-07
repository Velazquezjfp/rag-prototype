import json

import httpx
import pytest
from fake_search_client import FakeLLM

from rag_retrieval.chat import NO_EVIDENCE_ANSWER, ChatClient, answer, rewrite_question
from rag_retrieval.embed import EmbeddingError, QuestionEmbedder
from rag_retrieval.llm_http import LLMClient, LLMHTTPError
from rag_retrieval.models import Diagnostics, Message, RetrievalResult
from rag_retrieval.settings import EmbeddingSettings, LLMSettings


def _embedding_transport(dim=8, fail_first_with: int | None = None, seen: list | None = None):
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if seen is not None:
            seen.append(request)
        if fail_first_with and state["calls"] == 1:
            return httpx.Response(fail_first_with, text="busy")
        payload = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * dim}], "model": payload["model"]})

    return httpx.MockTransport(handler), state


def test_embedder_bearer_prefix_and_dim():
    seen: list[httpx.Request] = []
    transport, _ = _embedding_transport(dim=8, seen=seen)
    s = EmbeddingSettings(base_url="http://llm/v1", api_key="k", model="bge-m3", dim=8, query_prefix="query: ")
    emb = QuestionEmbedder.from_settings(s, transport=transport)
    vec = emb.embed("Frage")
    assert len(vec) == 8 and vec[0] == 0.1
    req = seen[0]
    assert req.headers["authorization"] == "Bearer k" and req.url.path == "/v1/embeddings"
    assert json.loads(req.content) == {"model": "bge-m3", "input": ["query: Frage"]}
    assert emb.client._client.trust_env is False
    assert emb.probe() == {"ok": True, "model": "bge-m3", "dim": 8}


def test_embedder_dim_mismatch_and_probe_error():
    transport, _ = _embedding_transport(dim=4)
    emb = QuestionEmbedder.from_settings(EmbeddingSettings(base_url="http://llm/v1", dim=8), transport=transport)
    with pytest.raises(EmbeddingError, match="dim 4 != configured 8"):
        emb.embed("x")
    assert emb.probe()["ok"] is False and "dim" in emb.probe()["error"]


def test_retry_on_503_then_success():
    transport, state = _embedding_transport(dim=8, fail_first_with=503)
    client = LLMClient("http://llm/v1", None, 5.0, max_attempts=3, backoff_s=0.0, transport=transport)
    emb = QuestionEmbedder(client, model="m", dim=8)
    assert len(emb.embed("x")) == 8 and state["calls"] == 2


def test_no_retry_on_400():
    transport = httpx.MockTransport(lambda r: httpx.Response(400, text="bad"))
    client = LLMClient("http://llm/v1", None, 5.0, max_attempts=3, backoff_s=0.0, transport=transport)
    with pytest.raises(LLMHTTPError) as exc:
        client.post_json("/embeddings", {})
    assert exc.value.status == 400


def _chat_transport(reply="Hallo Welt", sse=False, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        if seen is not None:
            seen.append(json.loads(request.content))
        if sse:
            chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': tok}}]})}\n\n" for tok in reply.split("|")]
            body = ": keep-alive\n\n" + "".join(chunks) + "data: {\"choices\": [{\"delta\": {}}]}\n\ndata: [DONE]\n\n"
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": reply}, "finish_reason": "length" if reply.endswith("…") else "stop"}], "usage": {"completion_tokens": 7}, "model": "m-1"})

    return httpx.MockTransport(handler)


def test_chat_complete_payload_and_probe():
    seen: list = []
    llm = ChatClient(LLMSettings(base_url="http://llm/v1", api_key="k", model="gemini-dev", temperature=0.0, max_tokens=99), transport=_chat_transport("Antwort.", seen=seen))
    assert llm.complete([{"role": "user", "content": "hi"}]) == "Antwort."
    assert seen[0] == {"model": "gemini-dev", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0, "max_tokens": 99}
    assert llm.complete([{"role": "user", "content": "hi"}], model="granite4", max_tokens=5)  # override works
    assert seen[1]["model"] == "granite4" and seen[1]["max_tokens"] == 5
    assert llm.probe() == "ok"
    llm.close()


def test_chat_complete_full_reports_truncation():
    llm = ChatClient(LLMSettings(base_url="http://llm/v1", model="m"), transport=_chat_transport("abgeschnitten…"))
    c = llm.complete_full([{"role": "user", "content": "x"}])
    assert c.text == "abgeschnitten…" and c.truncated and c.finish_reason == "length" and c.usage == {"completion_tokens": 7} and c.model == "m-1"
    assert not ChatClient(LLMSettings(base_url="http://llm/v1", model="m"), transport=_chat_transport("ok")).complete_full([{"role": "user", "content": "x"}]).truncated


def test_chat_stream_parses_sse_deltas():
    llm = ChatClient(LLMSettings(base_url="http://llm/v1", model="m"), transport=_chat_transport("Hal|lo| Welt", sse=True))
    assert list(llm.stream([{"role": "user", "content": "x"}])) == ["Hal", "lo", " Welt"]


def test_rewrite_without_history_does_not_call_the_model():
    llm = FakeLLM("egal")
    rw = rewrite_question([], "Wer ist zuständig?", llm)
    assert rw.rewritten == "Wer ist zuständig?" and rw.used_llm is False and llm.calls == []


def test_rewrite_uses_last_turns_and_strips_quotes():
    llm = FakeLLM('"Wer ist für Keycloak zuständig?"\nZweite Zeile ignoriert')
    history = [Message(role="user", content="Wer ist für Vault zuständig?"), Message(role="assistant", content="Marcel Ebert. " * 100), {"role": "user", "content": "alt"}, {"role": "assistant", "content": "alt"}]
    rw = rewrite_question(history[-2:] + history[:2], "und bei Keycloak?", llm, max_turns=2)
    assert rw.rewritten == "Wer ist für Keycloak zuständig?" and rw.used_llm and rw.error is None
    sent = llm.calls[0]
    assert sent[0]["role"] == "system" and "Letzte Frage: und bei Keycloak?" in sent[1]["content"]
    assert "Nutzer: Wer ist für Vault zuständig?" in sent[1]["content"]
    assert "…" in sent[1]["content"]  # long assistant turn truncated


def test_rewrite_falls_back_on_error_or_nonsense():
    bad = FakeLLM(fail=LLMHTTPError("down", 503))
    rw = rewrite_question([Message(role="user", content="a")], "und?", bad)
    assert rw.rewritten == "und?" and rw.used_llm and "down" in rw.error
    silly = FakeLLM("x" * 5000)
    assert rewrite_question([Message(role="user", content="a")], "und?", silly).error == "implausible rewrite"
    assert rewrite_question([Message(role="user", content="a")], "und?", FakeLLM("   ")).error == "implausible rewrite"


def _weak_result(weak=True):
    return RetrievalResult(question="q", mode="fast", weak_evidence=weak, weak_evidence_reason="r" if weak else None, diagnostics=Diagnostics(question="q", mode="fast"))


def test_answer_short_circuits_on_weak_evidence():
    llm = FakeLLM("sollte nicht kommen")
    assert answer(_weak_result(), "q", llm) == NO_EVIDENCE_ANSWER
    assert list(answer(_weak_result(), "q", llm, stream=True)) == [NO_EVIDENCE_ANSWER]
    assert llm.calls == []
    assert answer(_weak_result(), "q", llm, force=True) == "sollte nicht kommen" and len(llm.calls) == 1


def test_answer_calls_model_with_context_and_streams():
    llm = FakeLLM("Antwort [BHB-PLT-0007 S. 1].")
    out = answer(_weak_result(weak=False), "Frage?", llm, [Message(role="user", content="h")], stream=False)
    assert out.startswith("Antwort")
    msgs = llm.calls[0]
    assert msgs[0]["role"] == "system" and msgs[1] == {"role": "user", "content": "h"} and msgs[-1]["content"].endswith("Frage: Frage?")
    tokens = list(answer(_weak_result(weak=False), "Frage?", llm, stream=True))
    assert "".join(tokens).strip() == "Antwort [BHB-PLT-0007 S. 1]."
    with pytest.raises(ValueError):
        answer(_weak_result(weak=False), "Frage?", llm, context_limit_tokens=5)
