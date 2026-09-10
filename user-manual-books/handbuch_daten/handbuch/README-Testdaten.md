# Testdaten: fünf Betriebshandbücher (PDF) mit Diagrammen

Vollständig **fiktive** Testdaten. Grundlage waren drei anonymisierte Confluence-Exporte;
Behörde, Dienstleister, Standorte, Verfahren, Personen, Hostnamen, IP-Adressen sowie
Vorgangs- und Vertragsnummern sind erfunden. Fachliche Themen, Gliederung und Detailtiefe
der Vorlagen sind erhalten. Zwei weitere Handbücher (CaaS-Plattform, Zentrale
Sicherheitsdienste) sind vollständig neu geschrieben: Sie beschreiben die Dienste, auf die
sich die drei Verfahrenshandbücher berufen, und schließen den Graphen.

## Verwendete fiktive Namen

| Rolle | Name |
|---|---|
| Behörde | Bundesamt für Verfahrensdienste (**BAVD**), interne Zone `bavd.intern` |
| Infrastrukturdienstleister | **ZRB** – Zentrales Rechenzentrum des Bundes (Serviceklasse Bronze) |
| Standorte | Metro-Region **West** (Brandabschnitte WE-A / WE-B), Hausnetz **Süd** |
| Nabendienst 1 | **CaaS** – Container-Plattform als Dienst (`BHB-PLT-0001`) |
| Nabendienst 2 | **ZSD** – Zentrale Sicherheitsdienste: IAM, PKI, Vault (`BHB-PLT-0007`) |
| Verfahren 1 | **Event-System 2.0** (Plattformkomponente für Ereignisverteilung, `BHB-PLT-0042`) |
| Verfahren 2 | **Mars** – Modulares Antrags- und Registrierungssystem, hier die *Mars Dokumentendienste* (`BHB-VRF-0118`) |
| Verfahren 3 | **VPP** – Verfahrensportal Prüfprozesse (engl. *Audit Processes Portal*, `BHB-VRF-0207`) |
| Archiv-Schnittstelle | Dienst `archivline`, Keystore `/opt/archivline/conf/archivline.p12` |
| Nachbarsysteme | **ZPS** (Zentrale Poststelle), **BEP** (Behördliches Elektronisches Postfach), **AntragOnline**, Task-Manager, DTP |
| Dienstleister | Talwerk IT-Services GmbH, Steinbach Digital GmbH, Kranich Software GmbH |
| Archivprodukt | **ArchivLine 2023.3** |

Produktnamen Dritter (OpenShift, Kafka, Keycloak, Oracle, Tomcat, F5, Grafana, Vault …)
sind absichtlich echt geblieben — sie sind für die Technologie-Entitäten der Ontologie
nützlich und verweisen nicht auf eine bestimmte Organisation.

## Inhalt

| Datei | Umfang | Inhalt |
|---|---|---|
| `Betriebshandbuch_Event-System_2.0.pdf` | 49 S., 7 Abb., 45 Tab. | Eventgetriebene Plattformkomponente auf OpenShift + Kafka |
| `Betriebshandbuch_Mars_Dokumentendienste.pdf` | 50 S., 7 Abb., 42 Tab. | Dokumentenannahme, OCR, Ablage, Langzeitarchivierung |
| `Betriebshandbuch_VPP.pdf` | 50 S., 7 Abb., 37 Tab. | Klassische Webanwendung: Apache/Tomcat/Oracle, Keycloak, F5 |
| `Betriebshandbuch_CaaS-Plattform.pdf` | 27 S., 3 Abb., 19 Tab. | Container-Plattform: Mandanten, Knotenwartung, Auswirkungen, Kaltstart |
| `Betriebshandbuch_ZSD.pdf` | 29 S., 3 Abb., 15 Tab. | IAM (Keycloak), interne PKI, Vault; Konsumenten- und Auswirkungsmatrix |
| `canon.md` | — | Referenzdatenblatt: alle Entitäten, Rollen, Netze, Verträge, die bewusst gesetzten Kopplungen und Nicht-Kopplungen sowie die Partnervorgang-Matrix |
| `diagramme-png.zip` | 27 PNG | dieselben Diagramme in Originalauflösung (ca. 4 500 px Breite) |

## Für die Ontologie und den Knowledge Graph

`canon.md` beschreibt die bewusst gesetzten Merkmale (Abschnitt 7 für die drei Verfahren,
Abschnitt 9 für die beiden Nabendienste, Abschnitt 10 für die Partnervorgänge). Kurz:

* **Zwei Nabenknoten.** Die CaaS-Plattform und die Zentralen Sicherheitsdienste sind die
  Dienste, auf die sich alle drei Verfahrenshandbücher berufen. Beide Handbücher beschreiben
  dieselben Vorgänge aus der Sicht des Erbringers — jeder Konsument ist namentlich, mit
  Namespace, IAM-Client, Zertifikatsverfahren, Vault-Pfad und Handbuchkennung genannt.
* **Zwei zentrale Verknüpfungstabellen.** `BHB-PLT-0007` Tabelle 6 (Konsumentenmatrix:
  wer nutzt welchen Client, welchen Vault-Pfad, welches Zertifikatsverfahren) und
  `BHB-PLT-0001` Tabelle 12 (Auswirkung von Plattformereignissen je Mandant). Sie sind der
  direkte Weg von „ich starte X neu“ zu „das trifft Y und Z“.
* **Kaltstartreihenfolge des Gesamtverbunds.** `BHB-PLT-0001` Tabelle 13 (elf Schritte, mit
  Verantwortlichen, Dauer und Voraussetzung), aus `SOP-ZSD-06` gegengelesen — eine Kette,
  die alle fünf Dokumente verbindet.
* **Dokumentierte Ringabhängigkeit.** Vault läuft auf der Plattform, die Plattform bezieht
  ihre Zertifikate von der PKI, die PKI hinterlegt Material in Vault. Auflösung in beiden
  Handbüchern beschrieben (IAM und PKI laufen nicht auf der Plattform, Unseal ist manuell).
* **Geteilte Entitäten:** interne PKI (`BAVD Issuing CA 3`), Keycloak-Realm `bavd-intern`,
  Vault, Jumphost, Backupsystem, Jira/Confluence/Mattermost, ZRB-Serviceklasse Bronze.
* **Geteilte Personen:** Sabine Wollmer (PKI, 5 Dokumente), Kai Ostermann (IAM, 5),
  Frank Dettmer (Netz, 4), Andreas Wehrle (Plattform, 4), Marcel Ebert (Vault, 3),
  Dr. Martina Kellerhoff und Dr. Annika Reuß (Bereichsleitungen), Petra Nowak (Oracle, 2).
* **Echte fachliche Kopplung:** Die Mars Dokumentendienste veröffentlichen Ereignisse über
  das Event-System (Broker `dd-prod-broker`, Trigger `dd-archiv-events` ausgehend,
  `dd-task-events` eingehend) — in beiden Handbüchern aus eigener Perspektive beschrieben.
* **Bewusste Nicht-Kopplung:** VPP nutzt das Event-System nicht, ist kein Mandant der
  CaaS-Plattform und bleibt von einem Vault-Ausfall unberührt; ein IAM-Vollausfall trifft die
  Datenebene des Event-Systems nicht, nur das Ops-Cockpit; die Kafka-Broker liegen außerhalb
  der Plattform. Alle Aussagen stehen explizit im Text — geeignet zum Prüfen, ob eine
  Pipeline Negationen erkennt. In `BHB-PLT-0001` Tabelle 12 ist die VPP-Spalte durchgehend
  „keine“, mit Begründung darunter.
* **Partnervorgänge (Kanten in beide Richtungen):** sieben Vorfälle sind in zwei oder drei
  Handbüchern aus unterschiedlicher Sicht beschrieben, jede Seite nennt die Vorgangsnummer
  der Gegenseite (`ZSDSUP-0119`⇄`DDSUP-0794`, `ZSDSUP-0208`⇄`VPPSUP-2251`,
  `ESSUP-1455`→`ZSDSUP-0214`→`ESSUP-1517`, `CAASUP-0338`⇄`DDSUP-1195`,
  `CAASUP-0342`⇄`ESSUP-1588`, `CAASUP-0351`⇄`ZSDSUP-0247`⇄`DDSUP-1201`). Vollständige
  Liste in `canon.md`, Abschnitt 10.
* **Dieselbe Zahl aus zwei Sichten:** Für den Vault-Vorfall am 02.07.2026 nennt der
  Plattformbetrieb 48 Minuten, der ZSD-Betrieb 38 Minuten — der Unterschied ist im Text
  ausdrücklich erklärt (unterschiedliche Messpunkte). Nützlich, um zu prüfen, ob eine
  Pipeline widersprüchlich *aussehende* Werte richtig auflöst.
* **Ein Problem, drei Lösungswege:** TLS-Erneuerung vollautomatisch (Event-System,
  cert-manager/ACME), gemischt (Dokumentendienste) und vollständig manuell (VPP, keytool) —
  der Antragsweg selbst steht in `BHB-PLT-0007`, Kapitel 5.4.
* **Widerspruchsfrei, aber unterschiedlich:** je Dokument eigene Verfügbarkeits-, RTO/RPO-
  und Wartungsfensterwerte, eigene Jira-Projekte (`ESSUP`, `DDSUP`, `VPPSUP`, `CAASUP`,
  `ZSDSUP`), eigene SOP-Nummernkreise, eigene Dienstleister.

## Beispielfragen, die der Verbund beantwortet

* „Wie erneuere ich ein TLS-Zertifikat?“ → drei verschiedene Wege, je nach Verfahren,
  plus der zentrale Antragsprozess und der CA-Wechsel mit Truststore-Reihenfolge.
* „Ich will den Dispatcher neu starten — was hängt daran?“ → PodDisruptionBudget der
  Plattform, Vault-Abhängigkeit beim Podstart, Nachwirkung auf die Zustellung, Vorgänge
  `CAASUP-0342` und `ESSUP-1588` als Präzedenzfall.
* „Wer ist mein Ansprechpartner für X?“ → je Dienst und je Mandant namentlich, mit
  Durchwahl, Postfach, Chat-Kanal, Jira-Projekt und Eskalationsstufe.
* „Was passiert, wenn Vault versiegelt ist?“ → Auswirkung je Mandant, warum VPP nicht
  betroffen ist, wer entsiegeln darf und wie lange es gedauert hat.
* „In welcher Reihenfolge fährt der Verbund nach einem Totalausfall an?“ → elf Schritte
  über alle fünf Dokumente.

## Kennzeichnung als Testdaten

Jede Seite trägt im Kopf die Zeile **TESTDOKUMENT · DIESES DOKUMENT IST FIKTIV · KEINE
ECHTEN BETRIEBSDATEN**, darunter Titel und Dokumentkennung mit Version. Auf der Titelseite
steht zusätzlich in der Zeile „Klassifizierung“ der Vermerk *intern · Testdokument – fiktive
Daten*. Die Kopfzeile ist Text, kein Bild: Sie erscheint bei der Extraktion in jeder
Seiten- bzw. Chunk-Repräsentation und kann als Merkmal ausgewertet oder beim Chunking
bewusst entfernt werden.

## Hinweis zur Diagrammextraktion

Die Diagramme sind mit dreifacher Auflösung eingebettet (ca. 4 500 px Breite), im
Seitenlayout aber nur 180 mm breit. Wird beim Parsen mit einem zu niedrigen Renderfaktor
gearbeitet, werden die Beschriftungen unlesbar. Für Docling deshalb `images_scale >= 3.0`
setzen (entspricht ca. 216 dpi); die Bilder in `diagramme-png.zip` sind die Originale und
eignen sich als Referenz oder als direkter vLLM-Input.

Kennungen (Vorgangs-, SOP-, Firewall- und Dokumentnummern) sind im Satz gegen
Zeilenumbrüche geschützt, damit sie bei der Extraktion nicht in zwei Tokens zerfallen
(`CAASUP-` / `0338`).

## Diagrammtypen je Handbuch

**Verfahrenshandbücher (7 Abbildungen je Dokument):** Kontextdiagramm ·
Deployment-/Systemdiagramm · Netz- und Zonenarchitektur mit Portmatrix · Sequenzdiagramm
eines fachlichen Ablaufs · Release-/Schwenkprozess mit Rollen-Swimlanes ·
Zertifikatserneuerung als Ablaufdiagramm · Sicherungs- und Wiederherstellungskonzept.
Zusätzlich beim Event-System: interne Komponentenübersicht und Observability-Datenfluss;
bei VPP: Störungs-Entscheidungsbaum und Umgebungsvergleich.

**Nabenhandbücher (3 Abbildungen je Dokument):** CaaS — Plattformübersicht mit Mandanten
und Kontingenten, Knotenwartung als Swimlane-Prozess mit Auswirkungstabelle,
Abhängigkeits- und Kaltstartdiagramm mit hervorgehobener Ringabhängigkeit. ZSD —
Architektur der drei Dienste mit allen Konsumenten und Protokollen, Zertifikats-Lebenszyklus
über fünf Phasen und vier Bahnen, Auswirkungsmatrix aus fünf Ereignissen × vier Konsumenten.
