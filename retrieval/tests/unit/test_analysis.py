"""REQ-002 R6: the ``<einordnung>`` block is taken off the stream however the deltas are cut; anything that is not a
complete block passes through untouched."""

from __future__ import annotations

import pytest

from rag_retrieval.analysis import AnalysisSplitter, parse_analysis, split_analysis

BLOCK = "<einordnung>\nAufgabe: Skript\nBereich: innerhalb\nSystem: ZSD (BHB-PLT-0007)\nGrundlage: Handbücher, Verlauf\n</einordnung>"
ANSWER = "#!/bin/sh\nvault operator unseal\n"
REPLY = BLOCK + "\n\n" + ANSWER
FENCED = "\n```\n" + BLOCK + "\n```\n\n" + ANSWER


def _chunks(text: str, n: int) -> list[str]:
    return [text[i : i + n] for i in range(0, len(text), n)]


@pytest.mark.parametrize(
    "pieces",
    [
        [REPLY],
        _chunks(REPLY, 1),
        _chunks(REPLY, 7),
        ["<einord", "nung>\nAufgabe: Skript\nBereich: innerhalb\nSystem: ZSD (BHB-PLT-0007)\nGrundlage: Handbücher, Verlauf\n</einord", "nung>\n\n" + ANSWER],
        [FENCED],
        _chunks(FENCED, 3),
    ],
)
def test_splitter_takes_the_block_off_the_stream(pieces):
    sp = AnalysisSplitter(iter(pieces))
    assert "".join(sp) == ANSWER
    a = sp.analysis
    assert a is not None and a.task == "Skript" and a.in_scope is True and a.systems == "ZSD (BHB-PLT-0007)"
    assert a.basis == ["Handbücher", "Verlauf"] and a.fields["aufgabe"] == "Skript"
    assert a.summary_de() == "Aufgabe: Skript · Bereich: innerhalb · System: ZSD (BHB-PLT-0007) · Grundlage: Handbücher, Verlauf"
    assert a.as_dict()["in_scope"] is True and a.as_dict()["raw"].startswith("Aufgabe: Skript")


@pytest.mark.parametrize(
    "pieces",
    [
        ["Der Vault ", "ist versiegelt [BHB-PLT-0007 S. 19]."],
        _chunks("Der Vault ist versiegelt.", 1),
        ["<b>fett</b> und weiter"],
        [" " * 60],  # whitespace beyond the head budget flushes
        ["<einordnung>\nAufgabe: Skript\n" + "x" * 1600],  # never closed -> passthrough, no analysis
        _chunks("<einordnung>\nAufgabe: Skript\n" + "x" * 1600, 50),
        ["Einordnung: Aufgabe Skript\nAntwort."],  # no tags -> plain text
    ],
)
def test_text_without_a_complete_block_passes_through_unchanged(pieces):
    sp = AnalysisSplitter(iter(pieces))
    assert "".join(sp) == "".join(pieces) and sp.analysis is None


def test_out_of_scope_block_and_refusal():
    reply = "<einordnung>\nAufgabe: Sonstiges\nBereich: außerhalb\nSystem: unklar\nGrundlage: Fachwissen\n</einordnung>\nDabei kann ich nicht helfen."
    a, rest = split_analysis(reply)
    assert a is not None and a.in_scope is False and a.systems is None and a.basis == ["Fachwissen"] and a.task == "Sonstiges"
    assert rest == "Dabei kann ich nicht helfen." and a.summary_de() == "Aufgabe: Sonstiges · Bereich: außerhalb · Grundlage: Fachwissen"
    assert split_analysis("kein Block") == (None, "kein Block")
    assert split_analysis("<einordnung>\nAufgabe: x\n") == (None, "<einordnung>\nAufgabe: x\n")


def test_parse_is_tolerant_to_case_and_option_lists():
    a = parse_analysis("AUFGABE: Befehle anpassen\nbereich: Innerhalb\nSystem : CaaS\nGrundlage: fachwissen und Handbücher\nUnbekannt ohne Doppelpunkt")
    assert a.task == "Befehle" and a.in_scope and a.systems == "CaaS" and a.basis == ["Handbücher", "Fachwissen"]
    assert parse_analysis("Aufgabe: Rezept").task == "Sonstiges" and parse_analysis("").in_scope is True


def test_splitter_proxies_finish_reason_and_close():
    class Inner:
        finish_reason = "length"
        model = "m-1"
        closed = False

        def __iter__(self):
            yield from _chunks(REPLY, 5)

        def close(self):
            self.closed = True

    inner = Inner()
    sp = AnalysisSplitter(inner)
    assert "".join(sp) == ANSWER and sp.finish_reason == "length" and sp.truncated and sp.model == "m-1"
    sp.close()
    assert inner.closed is True
    assert AnalysisSplitter(iter(["x"])).finish_reason is None
