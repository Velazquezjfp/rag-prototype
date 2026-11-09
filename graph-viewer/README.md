# Graph-Viewer

Leichtgewichtige Browser-Ansicht der Graphen, die der docling-graph-Dienst pro Handbuch erzeugt
(`out/<lauf>/graph.json` bzw. das `graph`-Feld in `response.json`). Gezeigt werden Knoten (Label) und
Relationen; Attribute, Belegstellen und die Provenienz aus dem DoclingDocument erscheinen erst beim Anklicken.

## Start

```bash
python3 graph-viewer/serve.py            # Port 8010, nur lokal (127.0.0.1), liest ../out
python3 graph-viewer/serve.py --root /pfad/zu/anderen/laeufen --port 8010
```

Dann im Browser `http://localhost:8010/` öffnen. Läuft der Viewer auf einem anderen Rechner (VM, Server), von
dort per SSH-Tunnel holen und lokal `http://localhost:8010/` öffnen:

```bash
ssh -N -L 8010:localhost:8010 <user>@<rechner>
```

Unter WSL2 erreicht der Windows-Browser den Viewer in der Regel direkt über `http://localhost:8010/`.

Direkter Zugriff ohne Tunnel nur in vertrauenswürdigen Netzen (keine Anmeldung, unverschlüsseltes HTTP):
`--host 0.0.0.0 --allow-host <ip-der-vm>`; Port 8010 muss dann in der Firewall offen sein. Ohne `--allow-host`
weist der Server Aufrufe über die IP mit 403 ab (siehe *Sicherheit*).

Keine Installation nötig: der Server ist reine Python-Standardbibliothek (ab Python 3.8), die Seite bringt ihre
JavaScript-Bibliotheken unter `vendor/` mit (kein Internetzugriff zur Laufzeit).

## Sicherheit

Die Graphen enthalten Zitate und Chunk-Texte aus den Handbüchern (Hosts, Firewall-Regeln, Secret-Pfade). Der
Viewer ist ein Einzelplatz-Werkzeug, kein geteilter Dienst; zum Teilen gehört er hinter PAG/oauth2-proxy wie der Chat.

- **Bindung:** standardmäßig nur `127.0.0.1`; `0.0.0.0` muss ausdrücklich gesetzt werden und erzeugt eine Warnung.
- **Host-Header-Prüfung:** erlaubt sind `localhost`, `127.0.0.1`, `::1`, eine konkrete Bind-Adresse und alles
  aus `--allow-host`; alles andere bekommt 403. Das verhindert, dass eine fremde Webseite im selben Browser den
  Viewer per DNS-Rebinding ausliest.
- **Content-Security-Policy:** Skripte nur von diesem Server (`vendor/`) und das Inline-Skript von `index.html`,
  freigegeben per SHA-256-Hash. Der Hash wird bei jedem Seitenaufruf neu berechnet; Änderungen an `index.html`
  brauchen keinen Neustart. Inline-Event-Handler (`onclick="…"`) blockiert die Policy – Ereignisse daher immer mit
  `addEventListener` verdrahten. Keine Verbindungen außer zum eigenen Server, kein Einbetten in fremde Seiten.
- **Nur lesend:** ausschließlich GET; Pfade außerhalb von `--root` (auch über `..` oder Symlinks) werden abgewiesen.
- **Ausgabe:** alle Werte aus den Graph-Dateien werden vor dem Einfügen in HTML escaped; Chunk-Texte als reiner Text.

## Bedienung

- **Ordner** – alle Unterordner der Wurzel (bis zwei Ebenen tief) mit ihren Graph-Dateien. Als Graph gilt
  jede JSON-Datei mit `nodes` und `edges` (direkt oder unter `graph`); `chunks.json`, `summary.json` usw.
  erscheinen nicht. Die Liste wird bei jedem Klick auf „neu einlesen“ frisch vom Dateisystem gelesen, es
  gibt keinen Zwischenspeicher. Mehrere angehakte Dateien werden wie im Chat zu einem Graphen vereinigt:
  gleiche Knoten-Id = gleicher Knoten (`GraphStore` in `retrieval`), Knoten aus mehreren Handbüchern
  bekommen einen dickeren Rahmen und einen Schatten.
- **Isolierte Knoten** (ohne Relation; etwa die Hälfte aller Knoten) sind standardmäßig ausgeblendet.
- **Knotentypen / Relationen** – Filter; Farbe und Form kodieren die Gruppe des Typs
  (Technik blau · Organisation gelb/Pille · Störung magenta/abgeschrägt · Betrieb grün/Pfeil ·
  Dokumentation grau/gestrichelt). Negative Aussagen („NICHT …“) sind rot gestrichelt.
- **Klick auf Knoten oder Kante** – Detailspalte mit Typ, Id, Handbüchern, Attributen, Aliassen, Beleg
  (Zitat), Provenienz (Seiten, Abschnitt, DoclingDocument-Pfade) und Chunks; „Text anzeigen“ lädt den
  Chunk-Text aus `chunks.json` nach. Nachbarn sind anklickbar. Hintergrund-Klick oder `Esc` hebt die Auswahl auf.
- **Suche** – Label oder Alias; Treffer werden hervorgehoben, der Rest abgeblendet.
- **Layout neu / Einpassen / PNG speichern** – Layout ist fcose (kräftegesteuert) mit anschließendem
  Auseinanderschieben, sodass sich keine Knoten überlappen; isolierte Knoten werden gekachelt.

## API (für eigene Skripte)

| Pfad | Antwort |
|---|---|
| `GET /api/list` | Ordner und Graph-Dateien unter der Wurzel |
| `GET /api/graph?f=<pfad>&f=<pfad>` | vereinigter Graph (`nodes`, `edges`, `meta`) |
| `GET /api/chunks?folder=<ordner>&ids=<id,id>` | Chunk-Texte ohne Embeddings |

Pfade außerhalb der Wurzel werden abgewiesen.

## Vendor (MIT-Lizenz, einmalig heruntergeladen)

cytoscape 3.30.4 · cytoscape-fcose 2.2.0 · cose-base 2.2.0 · layout-base 2.0.1 · cytoscape-layout-utilities 1.0.0

Am 2026-11-09 gegen die npm-Pakete geprüft: byteidentisch, keine bekannten Schwachstellen (OSV). Prüfen mit
`sha256sum vendor/*.js`:

| Datei | SHA-256 |
|---|---|
| `cytoscape.min.js` (cytoscape 3.30.4, `dist/`) | `1bb5340e549511e111b31e5684872c949ad33d40ea5dba0ad8e7d90c62c7b3b9` |
| `cytoscape-fcose.js` | `4b1cab218d74996aa59cd8473f9239cc6398b8c1774d84d7e59ad9a68959cb57` |
| `cose-base.js` | `7cae9509bd36235a63a85e71c8d9fa2cd0bc1d0c1ecc5b5a737976f39d040ddf` |
| `layout-base.js` | `ec15ab5df9af3f20708f4faab994accf91cda71848cd5bb10a23432cc50b6745` |
| `cytoscape-layout-utilities.js` | `4791d09bb70edbb8d20c742b5cb255a9c4bdfa21d14d17945742b75dba4f1bab` |
