# Graph-Viewer

Leichtgewichtige Browser-Ansicht der Graphen, die der docling-graph-Dienst pro Handbuch erzeugt
(`out/<lauf>/graph.json` bzw. das `graph`-Feld in `response.json`). Gezeigt werden Knoten (Label) und
Relationen; Attribute, Belegstellen und die Provenienz aus dem DoclingDocument erscheinen erst beim Anklicken.

## Start

```bash
python3 graph-viewer/serve.py            # Port 8010, liest ../out
python3 graph-viewer/serve.py --root /pfad/zu/anderen/laeufen --port 8010
```

Dann im Browser `http://localhost:8010/` öffnen – oder von einem anderen Rechner (z. B. dem Laptop, wenn der
Server in der VM läuft) `http://<ip-der-vm>:8010/`. Der Server bindet an alle Schnittstellen (`0.0.0.0`);
Port 8010 muss in der VM-Firewall offen sein. Unter WSL2 erreicht der Windows-Host die VM über deren IP
(`hostname -I`) oder, bei „mirrored networking“, direkt über `localhost`.

Keine Installation nötig: der Server ist reine Python-Standardbibliothek, die Seite bringt ihre
JavaScript-Bibliotheken unter `vendor/` mit (kein Internetzugriff zur Laufzeit).

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
