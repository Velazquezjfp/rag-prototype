"""Erzeugt aus ontology.yaml ein Pydantic-v2-Modell und prüft die Ontologie.

Aufruf:
    python3 ontology_to_pydantic.py            # prüfen und Modell nach stdout
    python3 ontology_to_pydantic.py -o m.py    # Modell in Datei schreiben
    python3 ontology_to_pydantic.py --check    # nur prüfen

Der Generator ist absichtlich kurz: Er zeigt, dass die YAML-Datei vollständig
mechanisch auswertbar ist (Typen, Enums, Pflichtfelder, Listen, Relationen).
"""
import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).parent
ONTO = ROOT / "ontology.yaml"

# Datentypen mit Muster bekommen einen eigenen Alias im generierten Modul
ALIAS = {
    "duration": "Duration", "hostname": "Hostname", "ipv4": "IPv4", "cidr": "CIDR",
    "port": "Port", "phone_ext": "PhoneExt", "doc_id": "DocId", "ci_id": "CiId",
    "ticket_id": "TicketId", "sop_id": "SopId", "fw_id": "FwId",
    "openitem_id": "OpenItemId", "zone_id": "ZoneId", "contract_id": "ContractId",
    "vault_path": "VaultPath", "k8s_name": "K8sName",
}

PY_SCALAR = {
    "str": "str", "text": "str", "int": "int", "float": "float", "bool": "bool",
    "date": "_date", "duration": "str", "percent": "float", "hostname": "str",
    "ipv4": "str", "cidr": "str", "port": "int", "url": "str", "email": "str",
    "phone_ext": "str", "path": "str", "doc_id": "str", "ci_id": "str",
    "ticket_id": "str", "sop_id": "str", "fw_id": "str", "openitem_id": "str",
    "zone_id": "str", "contract_id": "str", "vault_path": "str",
    "k8s_name": "str", "reference": "str",
}


def load():
    return yaml.safe_load(ONTO.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Prüfungen
# --------------------------------------------------------------------------- #
def check(o):
    problems = []
    classes, enums, dts = o["classes"], o["enums"], o["datatypes"]
    mixins = o["mixins"]
    known_types = set(dts) | set(enums) | set(mixins) | set(classes)

    for cname, c in classes.items():
        if "pydantic" not in c:
            problems.append(f"{cname}: pydantic-Name fehlt")
        if "identity" not in c:
            problems.append(f"{cname}: identity fehlt (Merging über Dokumente unmöglich)")
        if not c.get("cues_de"):
            problems.append(f"{cname}: cues_de fehlt (Extraktor hat keinen Anker)")
        for f in c.get("fields", []):
            if f["type"] not in known_types:
                problems.append(f"{cname}.{f['name']}: unbekannter Typ {f['type']!r}")
            if "required" not in f:
                problems.append(f"{cname}.{f['name']}: required nicht gesetzt")
        # identity-Schlüssel müssen existierende Felder oder label/id sein
        own = {f["name"] for f in c.get("fields", [])} | {"label", "id"}
        for k in c["identity"].get("keys", []):
            if k not in own:
                problems.append(f"{cname}: identity-Schlüssel {k!r} ist kein Feld")

    for m, mx in mixins.items():
        for f in mx["fields"]:
            if f["type"] not in known_types:
                problems.append(f"mixin {m}.{f['name']}: unbekannter Typ {f['type']!r}")

    names = set()
    for r in o["relations"]:
        n = r["name"]
        if n in names:
            problems.append(f"Relation {n} doppelt")
        names.add(n)
        for side in ("source", "target"):
            vals = r[side] if isinstance(r[side], list) else [r[side]]
            for v in vals:
                if v not in classes and v not in mixins:
                    problems.append(f"{n}.{side}: unbekannte Klasse {v!r}")
        if "cardinality" not in r:
            problems.append(f"{n}: cardinality fehlt")

    # Kompetenzfragen müssen existierende Relationen/Felder nennen
    for q in o["competency_questions"]:
        for rel in re.findall(r"-([A-Z_]{3,})->", q.get("traversal", "")):
            if rel not in names:
                problems.append(f"{q['id']}: Traversal nennt unbekannte Relation {rel}")
        for kf in q.get("key_fields", []):
            cls = kf.split(".")[0]
            if cls not in classes and cls not in names:
                problems.append(f"{q['id']}: key_field {kf} zeigt auf {cls!r} — unbekannt")

    # Verneinungen müssen auf polarity-fähige Relationen zeigen
    for na in o["negative_assertions"]:
        if na["relation"] not in names:
            problems.append(f"negative_assertion: unbekannte Relation {na['relation']}")

    return problems


# --------------------------------------------------------------------------- #
# Codegenerierung
# --------------------------------------------------------------------------- #
EMITTED = set()


def pytype(f, o):
    t = f["type"]
    if t in o["enums"]:
        base = t
    elif t in o["mixins"]:
        base = o["mixins"][t]["pydantic"]
    elif t in o["classes"]:
        base = "str"          # Referenz über id
    elif t in ALIAS and ALIAS[t] in EMITTED:
        base = ALIAS[t]
    else:
        base = PY_SCALAR[t]
    if f.get("many"):
        return f"List[{base}]", "Field(default_factory=list)"
    if f.get("required"):
        return base, "..."
    return f"Optional[{base}]", "None"


def field_lines(fields, o, indent="    "):
    out = []
    for f in fields:
        typ, default = pytype(f, o)
        desc = (f.get("description") or "").replace('"', "'").strip()
        extra = f', description="{desc}"' if desc else ""
        if default == "...":
            out.append(f'{indent}{f["name"]}: {typ} = Field(...{extra})')
        elif default == "None":
            out.append(f'{indent}{f["name"]}: {typ} = Field(None{extra})')
        else:
            out.append(f'{indent}{f["name"]}: {typ} = Field(default_factory=list{extra})')
    return out or [f"{indent}pass"]


def generate(o):
    L = ['"""Automatisch erzeugt aus ontology.yaml — nicht von Hand ändern."""',
         "from __future__ import annotations",
         "", "from datetime import date as _date",
         "from enum import Enum",
         "from typing import Annotated, List, Literal, Optional, Union", "",
         "from pydantic import BaseModel, Field, StringConstraints", "", ""]

    L.append("# --- Basistypen mit Muster aus datatypes ---")
    for dt, spec in o["datatypes"].items():
        if not isinstance(spec, dict):
            continue
        alias = ALIAS.get(dt)
        if not alias:
            continue
        if spec.get("pattern"):
            EMITTED.add(alias)
            pat = spec["pattern"].replace("\\", "\\\\")
            L.append(f'{alias} = Annotated[str, StringConstraints(pattern=r"{spec["pattern"]}")]')
        elif "min" in spec and "max" in spec:
            EMITTED.add(alias)
            L.append(f'{alias} = Annotated[int, Field(ge={spec["min"]}, le={spec["max"]})]')
    L += ["", ""]

    for name, values in o["enums"].items():
        L.append(f"class {name}(str, Enum):")
        for v in values:
            L.append(f'    {v} = "{v}"')
        L += ["", ""]

    for name, mx in o["mixins"].items():
        L.append(f"class {mx['pydantic']}(BaseModel):")
        doc = (mx.get("description") or "").strip().replace('"', "'")
        if doc:
            L.append(f'    """{doc}"""')
        L += field_lines(mx["fields"], o) + ["", ""]

    base = o["mixins"]["NodeBase"]["pydantic"]
    for name, c in o["classes"].items():
        L.append(f"class {c['pydantic']}({base}):")
        doc = (c.get("description") or c.get("label_de") or "").strip().replace('"', "'")
        L.append(f'    """{doc}"""')
        L.append(f'    node_type: Literal["{name}"] = "{name}"')
        L += field_lines(c.get("fields", []), o) + ["", ""]

    rel_names = [r["name"] for r in o["relations"]]
    L.append("class RelationType(str, Enum):")
    for r in rel_names:
        L.append(f'    {r} = "{r}"')
    L += ["", ""]

    L.append(f"class Edge({o['mixins']['EdgeBase']['pydantic']}):")
    L.append('    """Kante des Graphen; type ist auf die Relationsliste beschränkt."""')
    L.append("    type: RelationType = Field(..., description='Relationsname')")
    L += ["", ""]

    node_union = ", ".join(c["pydantic"] for c in o["classes"].values())
    L += [f'AnyNode = Annotated[Union[{node_union}], Field(discriminator="node_type")]',
          "", "",
          "class GraphDocument(BaseModel):",
          '    """Extraktionsergebnis für ein Betriebshandbuch."""',
          "    document_id: str = Field(..., description='BHB-Kennung')",
          "    nodes: List[AnyNode] = Field(default_factory=list)",
          "    edges: List[Edge] = Field(default_factory=list)", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    o = load()
    problems = check(o)
    print(f"Klassen {len(o['classes'])} · Relationen {len(o['relations'])} · "
          f"Enums {len(o['enums'])} · Datentypen {len(o['datatypes'])}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} Befunde:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        sys.exit(1)
    print("Ontologie konsistent.", file=sys.stderr)

    if a.check:
        return
    code = generate(o)
    if a.out:
        pathlib.Path(a.out).write_text(code, encoding="utf-8")
        print(f"-> {a.out} ({len(code.splitlines())} Zeilen)", file=sys.stderr)
    else:
        print(code)


if __name__ == "__main__":
    main()