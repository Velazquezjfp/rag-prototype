"""Deutsche Textanalyse in Python — Nachbau des OpenSearch-Analyzers ``de_text``
(``opensearch-index/src/opensearch_index/mappings.py``):

    standard-Tokenizer → lowercase → stop (_german_) → german_normalization → light_german

Index und Frage müssen identisch zerlegt werden (SUCHSPEICHER-VERGLEICH.md §3.4). Die drei Lucene-Bausteine sind
aus dem Quelltext portiert (Lucene 10.5.0, wie im Container):

* ``StandardTokenizer``       – Wortgrenzen nach Unicode UAX #29 (hier als regulärer Ausdruck, siehe ``TOKEN_RE``)
* ``GermanNormalizationFilter`` – ß→ss, ä/ö/ü→a/o/u, ae/oe→a/o, ue→u (nicht nach Vokal oder q)
* ``GermanLightStemmer``      – UniNE-Light-Stemmer (Savoy): nur Suffixregeln

Die Stoppwortliste ist Lucenes ``org/apache/lucene/analysis/snowball/german_stop.txt`` (231 Wörter), unverändert.
Nur Standardbibliothek + ``regex`` (für ``\\p{L}``-Klassen).
"""

from __future__ import annotations

import regex

ANALYZER_VERSION = "de_text-1"

# --------------------------------------------------------------------------- 1. Tokenizer (UAX #29, vereinfacht)
# Ein Wort = Buchstaben/Ziffern/Verbinder (_). Dazwischen darf GENAU EIN Mittelzeichen stehen, wenn es zwischen zwei
# Buchstaben (. : ' · → "bavd.intern") oder zwei Ziffern (. , ; ' → "3.5", "1,5") steht. Bindestrich und / trennen.
_WORD = r"[\p{L}\p{M}\p{Nd}\p{Pc}]"
_MID_LETTER = "[.:'‘’·‧․]"  # MidLetter + MidNumLet + Single_Quote
_MID_NUM = "[.,;'‘’․⁄٬]"  # MidNum + MidNumLet + Single_Quote
TOKEN_RE = regex.compile(
    rf"{_WORD}+(?:(?:(?<=\p{{L}}){_MID_LETTER}(?=\p{{L}})|(?<=\p{{Nd}}){_MID_NUM}(?=\p{{Nd}})){_WORD}+)*",
    regex.V1,
)
MAX_TOKEN_LENGTH = 255  # Lucene StandardTokenizer: längere Tokens werden verworfen bzw. zerlegt


def tokenize(text: str) -> list[str]:
    return [m.group() for m in TOKEN_RE.finditer(text) if len(m.group()) <= MAX_TOKEN_LENGTH]


# --------------------------------------------------------------------------- 2. Stoppwörter (Lucene _german_)
STOPWORDS: frozenset[str] = frozenset(
    """
    aber alle allem allen aller alles als also am an ander andere anderem anderen anderer anderes anderm andern
    anderr anders auch auf aus bei bin bis bist da damit dann der den des dem die das daß derselbe derselben
    denselben desselben demselben dieselbe dieselben dasselbe dazu dein deine deinem deinen deiner deines denn
    derer dessen dich dir du dies diese diesem diesen dieser dieses doch dort durch ein eine einem einen einer
    eines einig einige einigem einigen einiger einiges einmal er ihn ihm es etwas euer eure eurem euren eurer
    eures für gegen gewesen hab habe haben hat hatte hatten hier hin hinter ich mich mir ihr ihre ihrem ihren
    ihrer ihres euch im in indem ins ist jede jedem jeden jeder jedes jene jenem jenen jener jenes jetzt kann
    kein keine keinem keinen keiner keines können könnte machen man manche manchem manchen mancher manches mein
    meine meinem meinen meiner meines mit muss musste nach nicht nichts noch nun nur ob oder ohne sehr sein
    seine seinem seinen seiner seines selbst sich sie ihnen sind so solche solchem solchen solcher solches soll
    sollte sondern sonst über um und uns unse unsem unsen unser unses unter viel vom von vor während war waren
    warst was weg weil weiter welche welchem welchen welcher welches wenn werde werden wie wieder will wir wird
    wirst wo wollen wollte würde würden zu zum zur zwar zwischen
    """.split()
)
assert len(STOPWORDS) == 231, len(STOPWORDS)


# --------------------------------------------------------------------------- 3. GermanNormalizationFilter (FSM-Port)
_N, _V, _U = 0, 1, 2  # ordinary · stops 'u' from entering umlaut state · umlaut state (allows e-deletion)


def german_normalize(token: str) -> str:
    out: list[str] = []
    state = _N
    for c in token:
        if c in "ao":
            out.append(c)
            state = _U
        elif c == "u":
            out.append(c)
            state = _U if state == _N else _V
        elif c == "e":
            if state != _U:  # im Umlaut-Zustand wird das e gelöscht (ae/oe/ue → a/o/u)
                out.append(c)
            state = _V
        elif c in "iqy":
            out.append(c)
            state = _V
        elif c == "ä":
            out.append("a")
            state = _V
        elif c == "ö":
            out.append("o")
            state = _V
        elif c == "ü":
            out.append("u")
            state = _V
        elif c == "ß":
            out.append("ss")
            state = _N
        else:
            out.append(c)
            state = _N
    return "".join(out)


# --------------------------------------------------------------------------- 4. GermanLightStemmer (Port)
_ACCENTS = str.maketrans("äàáâöòóôïìíîüùúû", "aaaaoooo" + "iiii" + "uuuu")


def _st_ending(ch: str) -> bool:
    return ch in "bdfghklmnt"


def _step1(s: str) -> str:
    n = len(s)
    if n > 5 and s.endswith("ern"):
        return s[:-3]
    if n > 4 and s[-2] == "e" and s[-1] in "mnrs":
        return s[:-2]
    if n > 3 and s[-1] == "e":
        return s[:-1]
    if n > 3 and s[-1] == "s" and _st_ending(s[-2]):
        return s[:-1]
    return s


def _step2(s: str) -> str:
    n = len(s)
    if n > 5 and s.endswith("est"):
        return s[:-3]
    if n > 4 and s[-2] == "e" and s[-1] in "rn":
        return s[:-2]
    if n > 4 and s.endswith("st") and _st_ending(s[-3]):
        return s[:-2]
    return s


def light_stem(token: str) -> str:
    return _step2(_step1(token.translate(_ACCENTS)))


# --------------------------------------------------------------------------- 5. Die Kette = Analyzer de_text
def analyze(text: str) -> list[str]:
    """Tokens genau wie ``POST /bhb-chunks/_analyze {"analyzer": "de_text"}`` (Abnahme: Golden-Test, §3.9)."""
    out: list[str] = []
    for tok in tokenize(text):
        t = tok.lower()
        if t in STOPWORDS:
            continue
        t = light_stem(german_normalize(t))
        if t:
            out.append(t)
    return out


def explain(text: str) -> list[dict[str, str]]:
    """Jeder Schritt einzeln — für die Darstellung im Notebook."""
    rows = []
    for tok in tokenize(text):
        low = tok.lower()
        stop = low in STOPWORDS
        norm = "" if stop else german_normalize(low)
        rows.append(
            {
                "token": tok,
                "lowercase": low,
                "stop": "✗ entfernt" if stop else "",
                "normalisiert": norm,
                "gestemmt": "" if stop else light_stem(norm),
            }
        )
    return rows


# --------------------------------------------------------------------------- 6. FTS5-Schicht
# FTS5 bekommt die fertigen Tokens als Text (durch Leerzeichen getrennt) und darf sie nicht weiter zerlegen:
# unicode61 mit tokenchars für die Mittelzeichen und den Unterstrich. Ein ASCII-Apostroph im Token lässt sich dort
# nicht sauber quoten → er wird für FTS5 konsistent (Index UND Frage) durch ’ ersetzt.
FTS5_TOKENIZE = "unicode61 remove_diacritics 0 tokenchars '.:_,;·‘’․‧⁄'"


def _fts_token(t: str) -> str:
    return t.replace("'", "’")


def fts_document(tokens: list[str]) -> str:
    """Spalteninhalt für ``INSERT INTO fts_x``."""
    return " ".join(_fts_token(t) for t in tokens)


def fts_query(tokens: list[str]) -> str:
    """``"t1" OR "t2" OR …`` — FTS5 verknüpft sonst mit UND, OpenSearch ``multi_match`` mit ODER (§3.3)."""
    return " OR ".join('"' + _fts_token(t).replace('"', '""') + '"' for t in tokens)
