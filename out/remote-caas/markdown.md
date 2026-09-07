BETRIEBSHANDBUCH

## CaaS - Container-Plattform als Dienst

Zentrale Container-Plattform des Bundesamtes für Verfahrensdienste OpenShift 4.16 · vier Umgebungen · 13 Mandanten

| Anwendung        | CaaS - Container-Plattform als Dienst           |
|------------------|-------------------------------------------------|
| CI-Nummer        | CI-PLT-0001                                     |
| Verantwortlicher | Andreas Wehrle (Bereich IT-B 1, Durchwahl 2140) |
| Vertretung       | Sonja Wiechert (Durchwahl 2143)                 |
| Fachseite        | Bereich IT-B 1 - Plattformbetrieb               |
| Dokument         | BHB-PLT-0001, Version 3.6                       |
| Stand            | 20. Juli 2026                                   |
| Klassifizierung  | intern · Testdokument - fiktive Daten           |

Herausgeber: Bundesamt für Verfahrensdienste (BAVD), Bereich IT-B 1 - Plattformbetrieb · Interne Dokumentation · Weitergabe nur an berechtigte Stellen

<!-- page break -->

## Inhaltsverzeichnis

## 1 Dokumentinformation

### Zweck und Geltungsbereich
### Zielgruppe
### Änderungshistorie
### Verwandte Dokumente

## 2 Kurzbeschreibung und Abgrenzung

### Leistung der Plattform
### Abgrenzung
### Kennzahlen

## 3 Systemüberblick

### Architektur
### Speicher
### Ingress, Egress und Service Mesh
### Vernetzung und Portmatrix

## 4 Mandanten und Verknüpfungen

### Mandantenübersicht
### Was bei welchem Mandanten hängt

## 5 Betrieb

### Servicezeiten und Wartungsfenster
### Zugänge und Rollen
### Knotenwartung: Neustart, Patch und Austausch (SOP-CAAS-01)
### Clusterupdate (SOP-CAAS-02)
### Zertifikate der Plattform (SOP-CAAS-04)
### Mandanten-Onboarding (SOP-CAAS-03)
### Standard Operating Procedures und regelmäßige Tätigkeiten

## 6 Abhängigkeiten und Auswirkungen

### Wovon die Plattform abhängt
### Auswirkungen von Plattformereignissen auf die Mandanten
- 6.3 Ringabhängigkeit Vault - PKI - Plattform
### Kaltstart des Gesamtverbunds (SOP-CAAS-06)

## 7 Troubleshooting

### Erste Prüfungen
### Entleeren eines Knotens bleibt stehen
### Vault nach Knotenwartung versiegelt (CAASUP-0351)
### Ingress-Wartung ohne Ankündigung (CAASUP-0342)
### Kontingent des Mandanten erschöpft (CAASUP-0338)
### Incident-Liste

## 8 Monitoring, Sicherung und Notfall

### Überwachung
### Sicherung und Wiederherstellung

<!-- page break -->

8.3 Notfall

## 9 Rollen, Verantwortlichkeiten und Eskalation

### Rollen
### Aufgabenteilung mit den Mandanten
### Eskalationsweg

## 10 Glossar und weiterführende Dokumente

### Glossar
### Weiterführende Dokumente

<!-- page break -->

## 1 Dokumentinformation

### 1.1 Zweck und Geltungsbereich

Dieses Betriebshandbuch beschreibt den Betrieb der Container-Plattform als Dienst (CaaS, CI-PLT-0001 ) des Bundesamtes für Verfahrensdienste. Die Plattform stellt den Fachverfahren und Plattformdiensten des Amtes standardisierte Laufzeitumgebungen auf Basis von Red Hat OpenShift bereit. Das Handbuch richtet sich an den Plattformbetrieb und an die Mandanten - also die Teams, die eigene Anwendungen auf der Plattform betreiben.

Im Geltungsbereich liegen die vier Cluster ocp-di , ocp-dev , ocp-test und ocp-prod mit ihren Knoten, der Speicherschicht (OpenShift Data Foundation), Ingress und Egress, dem Service Mesh, der GitOpsBereitstellung sowie den Verfahren zur Mandantenverwaltung. Nicht im Geltungsbereich: die Anwendungen der Mandanten und ihre Fachdaten, die von der Talwerk IT-Services GmbH betriebenen Kafka-Instanzen, die virtuellen Maschinen und Netzkomponenten des ZRB sowie sämtliche Verfahren, die nicht auf der Plattform laufen - insbesondere das VPP ( BHB-VRF-0207 ).

### 1.2 Zielgruppe

- Plattformbetrieb (Bereich IT-B 1) - Hauptadressat aller Handlungsanweisungen.
- Mandanten, insbesondere das Team Plattformdienste (Event-System 2.0) und der Systembetrieb Dokumentendienste - vor allem Kapitel 4, 5.3 und 6.
- Zentrale Sicherheitsdienste (ZSD) als Betreiber von Vault auf dieser Plattform und gleichzeitig Lieferant von IAM und PKI ( BHB-PLT-0007 ).
- ZRB als Erbringer der Virtualisierung sowie der Netzbetrieb (Frank Dettmer).

### 1.3 Änderungshistorie

Tabelle 1 hält die Fortschreibung dieses Handbuchs fest.

Tabelle 1: Änderungshistorie dieses Betriebshandbuchs

|   Version | Datum      | Autor          | Änderung                                                                                |
|-----------|------------|----------------|-----------------------------------------------------------------------------------------|
|       3.0 | 18.04.2025 | Andreas Wehrle | Neufassung nach Aufbau des vierten Clusters ocp-prod                                    |
|       3.2 | 21.11.2025 | Malte Grothe   | Speicherschicht auf OpenShift Data Foundation 4.16 umgestellt, Kapazitätsalarm ergänzt  |
|       3.3 | 16.03.2026 | Sonja Wiechert | Knotenwartung als SOP-CAAS-01 verbindlich beschrieben, Auswirkungstabelle aufgenommen   |
|       3.4 | 02.07.2026 | Sonja Wiechert | Abstimmungspflicht mit den Mandanten nach CAASUP-0342 verankert                         |
|       3.5 | 10.07.2026 | Ines Baumgart  | Portmatrix um FW-CAAS-009 bis 011 erweitert, Egress-Pool dokumentiert                   |
|       3.6 | 20.07.2026 | Andreas Wehrle | Kapitel 6 neu: Abhängigkeiten, Auswirkungen und Kaltstartreihenfolge des Gesamtverbunds |

<!-- page break -->

### 1.4 Verwandte Dokumente

Dieses Handbuch ist der gemeinsame technische Unterbau der Verfahrenshandbücher. Tabelle 2 nennt die Dokumente, mit denen es unmittelbar verzahnt ist.

Tabelle 2: Unmittelbar verwandte Dokumente

| Dokument                                     | Kennung          | Bezug                                                                                                                         |
|----------------------------------------------|------------------|-------------------------------------------------------------------------------------------------------------------------------|
| Betriebshandbuch Event-System 2.0            | BHB-PLT-0042     | Mandant mit vier Namespaces; PodDisruptionBudget des Dispatchers ist bei jeder Knotenwartung zu berücksichtigen (Kapitel 5.3) |
| Betriebshandbuch Mars Dokumentendienste      | BHB-VRF-0118     | Mandant mit drei Namespaces, RWX-Speicher für den Ingest-Spool, feste Egress-Adresse für den Datenbankzugriff                 |
| Betriebshandbuch Zentrale Sicherheitsdienste | BHB-PLT-0007     | liefert IAM, PKI und Vault; Vault ist gleichzeitig Mandant dieser Plattform (Ringabhängigkeit, Kapitel 6.3)                   |
| Betriebshandbuch VPP                         | BHB-VRF-0207     | ausdrücklich kein Mandant; gemeinsame Berührungspunkte sind nur IAM, PKI und die Netzzonen                                    |
| Servicekatalog Plattformdienste              | SK-PLT-1.9       | Leistungsbeschreibung, Kontingentklassen, Onboarding-Bedingungen                                                              |
| Zonenkonzept Verfahrensnetz                  | NET-ZK-004       | Zonendefinitionen, Grundlage der Portmatrix in Kapitel 3.4                                                                    |
| Leistungsschein ZRB                          | LS-ZRB-2022-5210 | Virtualisierung, Speicher- und Netzhardware, Serviceklasse Bronze                                                             |
| Notfallhandbuch Bereich IT-B                 | NFH-ITB-2.1      | Krisenstab und Meldewege, Grundlage für Kapitel 6.4                                                                           |

#### Hinweis zur Dokumentenlenkung

Gültige Fassung unter https://confluence.bavd.intern/display/CAAS/Betriebshandbuch . Alle genannten Personen, Hostnamen, IP-Adressen, Vorgangs- und Vertragsnummern sind Beispieldaten einer Erprobungsumgebung.

<!-- page break -->

## 2 Kurzbeschreibung und Abgrenzung

### 2.1 Leistung der Plattform

Die Plattform stellt Mandanten eine standardisierte Laufzeitumgebung für containerisierte Anwendungen bereit. Ein Mandant erhält einen oder mehrere Namespaces, ein Ressourcenkontingent, Rollen für seine Mitarbeitenden, eine Anbindung an die GitOps-Bereitstellung sowie Zugang zu den Querschnittsdiensten der Plattform: Ingress mit Zertifikatsautomatik, Egress mit fester Quelladresse, Speicherklassen, Service Mesh mit gegenseitiger TLS-Authentifizierung und Anschluss an die Observability.

Die Plattform ist ausdrücklich fachlich blind : Sie kennt weder die Anwendungen noch deren Daten. Umgekehrt greifen Mandanten nicht auf Knoten, Speicher oder Clusterkonfiguration zu. Diese Trennung ist die Grundlage der Zuständigkeitsregelungen in Kapitel 5 und 9.

### 2.2 Abgrenzung

- Keine Anwendungsbetreuung. Für Aufbau, Betrieb und Störungen einer Anwendung ist der jeweilige Mandant verantwortlich; das gilt auch für Kontingente, die eine Anwendung ausschöpft (siehe CAASUP-0338 in Kapitel 7.5).
- Keine virtuellen Maschinen. Knoten werden vom ZRB bereitgestellt. Die Plattform bestellt, konfiguriert und überwacht sie, betreibt aber keine Virtualisierung.
- Keine Middleware. Die Kafka-Instanzen des Event-Systems liegen außerhalb der Plattform im Hausnetz Süd und werden von der Talwerk IT-Services GmbH betrieben.
- Keine Identitäten und Zertifikate. IAM, PKI und Vault verantwortet der Bereich IT-S 1 ( BHB-PLT-0007 ). Die Plattform ist Konsument dieser Dienste - und im Fall von Vault gleichzeitig deren Wirt.
- Keine Datenbanken. Oracle-Instanzen der Verfahren laufen auf eigenen Maschinen im Datennetz; die Plattform stellt lediglich die Egress-Adresse für den Zugriff.

### 2.3 Kennzahlen

Tabelle 3 gibt den Betriebsumfang zum Stichtag 30.06.2026 wieder.

Tabelle 3: Betriebskennzahlen (Stand 30.06.2026)

| Kennzahl                   | Wert                  | Anmerkung                                           |
|----------------------------|-----------------------|-----------------------------------------------------|
| Cluster                    | 4                     | Dev-Intern, Dev, Test, Produktion                   |
| Knoten insgesamt           | 27 Worker, 12 Master  | 3 / 6 / 6 / 12 Worker je Cluster                    |
| Mandanten                  | 13                    | davon 11 mit Produktionsnamespaces                  |
| Namespaces                 | 47                    | über alle Cluster, ohne Systemnamespaces            |
| Laufende Pods (Produktion) | 1 180 im Mittel       | Tagesspitze 1 460, montags 07:00-09:00              |
| Routen                     | 96                    | alle mit Zertifikat aus der internen PKI            |
| Persistente Volumes        | 132                   | davon 18 im Modus RWX (CephFS)                      |
| Speicherbelegung           | 118 von 180 TB brutto | 66 Prozent, Alarm ab 75 Prozent                     |
| Verfügbarkeit Produktion   | 99,98 %               | Messzeitraum April 2025 bis März 2026, Ziel 99,95 % |
| Changes je Jahr            | 214                   | davon 46 mit Auswirkung auf Mandanten               |

<!-- page break -->

#### Gut zu wissen

Die gemessene Verfügbarkeit bezieht sich auf die Erreichbarkeit von API und Ingress, nicht auf die Anwendungen der Mandanten. Ein Mandant kann trotz verfügbarer Plattform gestört sein - und umgekehrt bleibt eine Anwendung bei einer Knotenwartung verfügbar, wenn sie über beide Brandabschnitte verteilt ist (Kapitel 5.3).

<!-- page break -->

## 3 Systemüberblick

### 3.1 Architektur

Abbildung 1 zeigt die vier Umgebungen, den Aufbau des Produktionsclusters über zwei Brandabschnitte und die Mandanten mit ihren Namespaces, Kontingenten und Handbüchern.

<!-- image -->

[Description] Das Diagramm stellt vier CaaS-Umgebungen (`ocp-di`, `ocp-dev`, `ocp-test`, `ocp-prod`) dar, wobei ein Pfeil mit der Beschriftung „Detailsicht“ das Produktionscluster in der `ZONE-APP-WE` hervorhebt, welches redundant über die beiden Brandabschnitte `WE-A` und `WE-B` mit Master-, Worker- und ODF-Speicherknoten sowie Plattform-VIPs aufgebaut ist. Horizontale Pfeile verbinden das Cluster mit dem Bereich der 13 Mandanten (u. a. Event-System 2.0, Mars Dokumentendienste, Vault und Observability) und visualisieren deren Zuweisung von Namespaces, Kontingenten und Handbuchreferenzen. Im unteren Bereich werden zudem Erbringer und Basisdienste (ZRB, ZSD, Talwerk) sowie das auf virtuellen Maschinen betriebene Verfahrensportal VPP als Nicht-Mandant der Plattform aufgeführt.

Abbildung 1: Plattformübersicht und Mandanten. Der Ausfall eines Brandabschnitts halbiert die Kapazität; laufende Arbeitslasten im verbleibenden Abschnitt arbeiten weiter. Beim Ausfall von WE-B bleibt das etcd-Quorum mit zwei von drei Mitgliedern erhalten; beim Ausfall von WE-A verliert die Steuerungsebene ihr Quorum (Kapitel 3.1).

Alle Cluster sind gleich aufgebaut und unterscheiden sich nur in der Anzahl der Knoten und in der Freigabepolitik der GitOps-Bereitstellung: In ocp-di und ocp-dev wird automatisch synchronisiert, ab ocptest nur nach Freigabe. Tabelle 4 nennt die Eckdaten.

Tabelle 4: Cluster und Knoten

| Cluster   | API-Endpunkt                   | Anwendungsdomäne           |   Worker |   Master | Verwendung                                                                 |
|-----------|--------------------------------|----------------------------|----------|----------|----------------------------------------------------------------------------|
| ocp-di    | api.di.caas.bavd.intern:6443   | apps.di.caas.bavd.intern   |        3 |        3 | Vorabprüfung von Operator- und Clusterversionen durch den Plattformbetrieb |
| ocp-dev   | api.dev.caas.bavd.intern:6443  | apps.dev.caas.bavd.intern  |        6 |        3 | Entwicklungsumgebung der Mandanten                                         |
| ocp-test  | api.test.caas.bavd.intern:6443 | apps.test.caas.bavd.intern |        6 |        3 | Test und Abnahme, Lasttests der                                            |

<!-- page break -->

| Cluster   | API-Endpunkt                   | Anwendungsdomäne           |   Worker |   Master | Verwendung Mandanten                        |
|-----------|--------------------------------|----------------------------|----------|----------|---------------------------------------------|
| ocp-prod  | api.prod.caas.bavd.intern:6443 | apps.prod.caas.bavd.intern |       12 |        3 | Produktion, Rufbereitschaft rund um die Uhr |

Alle Cluster stehen in der Metro-Region West in der Zone ZONE-APP-WE . In der Produktion verteilen sich die Knoten auf die Brandabschnitte WE-A ( 10.30.1.21-26 , zwei Master) und WE-B ( 10.30.2.21-26 , ein Master); die Kafka-Broker des Event-Systems liegen dagegen im Hausnetz Süd, der Zonenübergang ist in NET-ZK-007 beschrieben. Jeder Worker verfügt über 16 vCPU und 64 GiB Arbeitsspeicher. Die virtuellen Maschinen stellt das ZRB nach Leistungsschein LS-ZRB-2022-5210 bereit; die Lieferzeit für einen zusätzlichen Knoten beträgt zehn Arbeitstage.

#### Grenze der Standortverteilung

Die drei Mitglieder der Steuerungsebene liegen zwei zu eins auf WE-A und WE-B. Fällt WE-B aus, bleibt das etcdQuorum erhalten und die Plattform ist voll steuerbar. Fällt WE-A aus, verliert die Steuerungsebene ihr Quorum: Laufende Pods in WE-B arbeiten weiter und der Ingress bleibt erreichbar, es sind aber keine Änderungen, Neustarts und Verlagerungen möglich, bis ein drittes Mitglied wieder verfügbar ist oder etcd nach SOP-CAAS-06 aus dem Sicherungspunkt wiederhergestellt wird. Ein drittes Mitglied an einem eigenen Standort ist als offener Punkt OP-CAAS-01 vermerkt und setzt eine Leitungsanbindung mit weniger als fünf Millisekunden Umlaufzeit voraus.

### 3.2 Speicher

Die Speicherschicht ist OpenShift Data Foundation 4.16 auf Basis von Ceph. Tabelle 5 nennt die angebotenen Klassen. Mandanten wählen die Klasse im PersistentVolumeClaim; eine Änderung der Klasse ist nachträglich nicht möglich und erfordert eine Datenmigration durch den Mandanten.

Tabelle 5: Speicherklassen

| Klasse                      | Modus       | Eigenschaften                                       | Typische Nutzung                                                            |
|-----------------------------|-------------|-----------------------------------------------------|-----------------------------------------------------------------------------|
| ocs-storagecluster-ceph-rbd | RWO         | Blockspeicher, 3-fach repliziert, Snapshots         | Zustandsdaten des Event-System-Dispatchers, Datenbanken der Fachanwendungen |
| ocs-storagecluster-cephfs   | RWX         | Dateispeicher, 3-fach repliziert, mehrere Schreiber | Ingest-Spool der Dokumentendienste ( dd-spool-pvc , 500 GiB)                |
| ocs-storagecluster-ceph-rgw | Objekt (S3) | Objektspeicher, Erasure Coding 4+2                  | Observability-Daten, Protokollarchive der Mandanten                         |

Kapazität und Wachstum werden monatlich ausgewertet. Bei einer Belegung über 75 Prozent löst der Alarm OdfCapacityHigh aus; die Erweiterung erfolgt in Schritten von 20 TB über einen Change beim ZRB (SOP-CAAS-05).

### 3.3 Ingress, Egress und Service Mesh

Eingehender Verkehr erreicht die Plattform über den Ingress-VIP 10.30.8.7 (TCP 443). Die Zertifikate der Routen werden über cert-manager automatisch aus der internen PKI bezogen (ClusterIssuer bavd-issuingca-3 , Kapitel 5.5). Ausgehender Verkehr verlässt die Plattform über den Egress-Pool 10.30.9.40-43 ; die feste Quelladresse ist Voraussetzung für Firewall-Freischaltungen der Mandanten in Richtung Datennetz - die Regeln selbst gehören zum jeweiligen Verfahren, nicht zur Plattform.

<!-- page break -->

Innerhalb der Cluster kommuniziert jede Arbeitslast über das Service Mesh 2.6 mit gegenseitiger TLSAuthentifizierung. Zwischen den Brandabschnitten besteht kein Zonenübergang: Der Ost-West-Verkehr ist clusterintern und unterliegt keiner Firewall-Regel.

### 3.4 Vernetzung und Portmatrix

Tabelle 6 nennt die Regeln, die die Plattform selbst benötigt. Regeln der Mandanten (etwa FW-DD-008 für den Oracle-Zugriff der Dokumentendienste) sind im jeweiligen Verfahrenshandbuch dokumentiert. Änderungen erfolgen über einen Change beim Netzbetrieb (Frank Dettmer) mit fünf Arbeitstagen Vorlauf.

Tabelle 6: Portmatrix der Plattform

| Regel       | Quelle                    | Ziel                       | Port            | Zweck                                                     |
|-------------|---------------------------|----------------------------|-----------------|-----------------------------------------------------------|
| FW-CAAS-001 | ZONE-EXT                  | 10.30.8.7                  | TCP 443         | Zugriff auf die Routen der Mandanten                      |
| FW-CAAS-002 | ZONE-MGMT                 | 10.30.8.6                  | TCP 6443        | oc und kubectl , nur vom Jumphost jump01.mgmt.bavd.intern |
| FW-CAAS-003 | ZONE-MGMT                 | 10.30.1.0/24, 10.30.2.0/24 | TCP 22          | Knotenzugriff im Störungsfall, Vier-Augen-Prinzip         |
| FW-CAAS-004 | ZONE-APP-WE               | 10.20.6.40                 | TCP 443         | ACME-Anfragen des cert-manager an die PKI                 |
| FW-CAAS-005 | ZONE-APP-WE               | 10.20.6.20                 | TCP 443         | OIDC-Anmeldung an Konsole und API (Client caas-console )  |
| FW-CAAS-006 | ZONE-APP-WE               | 10.20.6.11-12              | TCP 636         | Gruppenauflösung über LDAPS                               |
| FW-CAAS-007 | ZONE-APP-WE               | nexus.bavd.intern          | TCP 443         | Bezug der Container-Images                                |
| FW-CAAS-008 | ZONE-APP-WE               | git.bavd.intern            | TCP 443         | GitOps-Abgleich durch ArgoCD                              |
| FW-CAAS-009 | ZONE-MGMT                 | 10.30.1.0/24, 10.30.2.0/24 | TCP 9100, 10250 | Abholung der Knotenmetriken                               |
| FW-CAAS-010 | ZONE-APP-WE               | bkp01.mgmt.bavd.intern     | TCP 8403        | Auslagerung der etcd-Snapshots                            |
| FW-CAAS-011 | Egress-Pool 10.30.9.40-43 | ZONE-DATA                  | je Mandant      | Sammelregel; die Einzelfreigaben führen die Mandanten     |

<!-- page break -->

## 4 Mandanten und Verknüpfungen

### 4.1 Mandantenübersicht

Tabelle 7 ist die zentrale Verknüpfungstabelle dieses Handbuchs: Sie ordnet jedem Mandanten seine Namespaces, sein Kontingent, seine Besonderheiten, den Ansprechpartner und das zugehörige Betriebshandbuch zu. Wer eine Änderung an der Plattform plant, arbeitet diese Tabelle von oben nach unten durch.

Tabelle 7: Mandanten der Produktionsumgebung

| Mandant                       | Namespaces                                                                    | Kontingent       | Besonderheit                                                                                                 | Ansprechpartner                    | Handbuch     |
|-------------------------------|-------------------------------------------------------------------------------|------------------|--------------------------------------------------------------------------------------------------------------|------------------------------------|--------------|
| Event-System 2.0              | knative-eventing, eventing-kafka-broker, event-system-ops, event-system-debug | 12 vCPU / 24 GiB | StatefulSet mit PodDisruptionBudget minAvailable=2 ; Verbindung nach außen zu Kafka im Hausnetz Süd          | Tobias Reinhardt, Jonas Brinkmann  | BHB-PLT-0042 |
| Mars Dokumentendienste        | dokumentendienste-prod, -test, -dev                                           | 24 vCPU / 48 GiB | RWX-Volume dd-spool-pvc (500 GiB); feste Egress-Adresse 10.30.9.40 für Oracle und Objektspeicher             | Christina Haberland, Rainer Kolbe  | BHB-VRF-0118 |
| Zentrale Sicherheitsdienste   | vault-system                                                                  | 6 vCPU / 12 GiB  | drei Vault-Knoten mit Raft-Storage; nach Verlust des Führungsknotens ist ein Entsiegeln erforderlich         | Marcel Ebert                       | BHB-PLT-0007 |
| Observability                 | obs-stack                                                                     | 16 vCPU / 40 GiB | Prometheus, Loki, Tempo und Grafana für alle Mandanten; Ausfall bedeutet Blindflug, nicht Betriebsstillstand | Miriam Falk                        | BHB-PLT-0042 |
| AntragOnline                  | antragonline-prod, -test                                                      | 20 vCPU / 40 GiB | Produzent von Ereignissen; Lastspitzen zum Monatsanfang                                                      | Fachanwendungsbetrieb              | -            |
| Task-Manager                  | taskmanager-prod, -test                                                       | 8 vCPU / 16 GiB  | Konsument von Ereignissen; antwortet mit HTTP 503 bei Überlast (siehe ESSUP-1482)                            | Fachanwendungsbetrieb              | -            |
| Benachrichtigungsdienst       | notify-prod                                                                   | 4 vCPU / 8 GiB   | Zustellung an Postfächer, SMTP-Relay                                                                         | Fachanwendungsbetrieb              | -            |
| Sechs weitere Fachanwendungen | je 1-2 Namespaces                                                             | 2-12 vCPU        | ohne besondere Anforderungen                                                                                 | siehe Mandantenliste in Confluence | -            |

<!-- page break -->

### 4.2 Was bei welchem Mandanten hängt

Event-System 2.0. Der Dispatcher ist ein StatefulSet mit drei Replikas und einem PodDisruptionBudget von minAvailable=2 . Beim Entleeren eines Knotens lässt sich deshalb nur eine Replika gleichzeitig verlagern; ein paralleles Entleeren zweier Knoten blockiert. Die Zustellung von Ereignissen verzögert sich dabei um bis zu drei Minuten, geht aber nicht verloren, weil die Ereignisse in Kafka liegen. Der Broker-Ingress ist unkritisch, solange er über beide Brandabschnitte verteilt ist. Mars Dokumentendienste. Der dd-ingest-worker zieht beim Start Zugangsdaten aus Vault. Ist Vault versiegelt, startet der Pod nicht - deshalb ist bei Knotenwartungen die Reihenfolge Vault zuerst, Mandanten danach einzuhalten. Der Ingest pausiert höchstens zwei Minuten; eingehende Stapel bleiben im Spool und werden anschließend abgearbeitet. Der Lesezugriff über dd-read-service bleibt mit vier Replikas durchgehend verfügbar. Zentrale Sicherheitsdienste (Vault). Vault ist gleichzeitig Mandant und Vorleistung. Wird der Knoten mit dem Führungsknoten entleert, wählt der Raft-Verbund einen neuen Führungsknoten; bleibt der Verbund unter zwei erreichbaren Knoten, ist ein manuelles Entsiegeln nötig (drei von fünf Schlüsselanteilen). Solange Vault versiegelt ist, können alle Mandanten keine neuen Pods starten. Dieser Fall ist am 02.07.2026 eingetreten (CAASUP-0351, Partnervorgang ZSDSUP-0247) und hat zur Sonderregel in SOP-CAAS-01 geführt. Observability. Ein Ausfall führt zu Messlücken und fehlenden Alarmen, nicht zu einem Betriebsstillstand. Bei geplanten Arbeiten am Observability-Stack ist die Rufbereitschaft zu informieren, weil in dieser Zeit keine automatische Alarmierung erfolgt. VPP. Kein Mandant. Das Verfahren läuft auf virtuellen Maschinen und ist von Knotenwartungen,

Clusterupdates und Speicherarbeiten nicht betroffen. Gemeinsam genutzt werden nur IAM, PKI und die Netzzonen - Auswirkungen dieser Dienste sind in BHB-PLT-0007 beschrieben.

#### Achtung

Kontingente sind harte Grenzen. Überschreitet eine Arbeitslast ihr Speicherlimit, beendet die Plattform den Pod - auch mitten in der Verarbeitung. Genau das führte am 17.06.2026 zum Abbruch der Aufbereitung großer Sammelakten bei den Dokumentendiensten (CAASUP-0338, Partnervorgang DDSUP-1195). Eine Erhöhung des Kontingents ist ein Change nach SOP-CAAS-03 mit fünf Arbeitstagen Vorlauf.

<!-- page break -->

## 5 Betrieb

### 5.1 Servicezeiten und Wartungsfenster

- Betriebszeiten: 24 Stunden an 7 Tagen für alle vier Cluster.
- Servicezeiten des Plattformbetriebs: Montag bis Freitag 07:30-17:30 Uhr.
- Rufbereitschaft: rund um die Uhr für ocp-prod , Alarmierung über den Servicedesk 0800 1180 100 .
- Wartungsfenster: Montag 20:00-00:00 Uhr. Änderungen mit Auswirkung auf Mandanten werden 10 Arbeitstage vorher im Kanal #caas-plattform und im Change angekündigt.
- Meldewege: Jira CAASUP , Kanal #caas-plattform , Postfach caas-betrieb@bavd.bund.de .

Die Wartungsfenster der Mandanten liegen bewusst an anderen Wochentagen - Event-System mittwochs ab 17:00, Dokumentendienste dienstags 18:00-22:00, VPP donnerstags 17:00-21:00. Eine Plattformwartung wird deshalb nie in einem Mandantenfenster durchgeführt und umgekehrt. Kollisionen werden im gemeinsamen Wartungskalender ( confluence.bavd.intern/display/CAAS/Wartungskalender ) sichtbar.

#### Achtung - Lehre aus CAASUP-0342

Am 24.06.2026 wurde der Ingress-Router außerhalb des Fensters und ohne Ankündigung neu gestartet. Der BrokerIngress des Event-Systems war elf Minuten nicht erreichbar; die Produzenten erhielten HTTP 503 (Partnervorgang ESSUP-1588). Seither gilt: kein Eingriff am Ingress, an der API oder an Knoten ohne Change und ohne Rückmeldung der betroffenen Mandanten.

### 5.2 Zugänge und Rollen

Die Anmeldung erfolgt ausschließlich über das IAM (Client caas-console , Realm bavd-intern ); lokale Clusterkonten sind nicht zugelassen. Die Gruppenzuordnung kommt aus dem Active Directory. Tabelle 8 nennt die Rollen.

Tabelle 8: Rollen und Berechtigungen

| Rolle (AD-Gruppe)          | Rechte                                                                                                                                     | Zugewiesen an                                 |
|----------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------|
| BAVD-CAAS-Admin            | Vollzugriff auf alle Cluster, Knotenverwaltung, Speicher, Netzobjekte                                                                      | Plattformbetrieb (4 Personen)                 |
| BAVD-CAAS- <Mandant>-Admin | Vollzugriff innerhalb der eigenen Namespaces, kein Zugriff auf Knoten oder andere Mandanten                                                | je Mandant, z. B. BAVD-CAAS-EventSystem-Admin |
| BAVD-CAAS-Lesen            | clusterweiter Lesezugriff auf Ressourcen und Ereignisse, keine Protokolle der Mandanten                                                    | Observability, Informationssicherheit         |
| svc-caas-argocd            | technisches Konto für die GitOps-Bereitstellung, ausschließlich deklarative Änderungen                                                     | ArgoCD                                        |
| brk-caas-admin             | Break-Glass-Konto mit lokalem Zertifikat für den Fall, dass das IAM nicht verfügbar ist; Nutzung nur im Vier-Augen-Prinzip und mit Vorgang | Andreas Wehrle, Sonja Wiechert                |

Knotenzugriff per SSH ist nur aus ZONE-MGMT über den Jumphost jump01.mgmt.bavd.intern und nur zur Störungsbehebung zulässig; jeder Zugriff wird protokolliert und im Vorgang begründet. Geheimnisse der Plattform liegen in Vault ( kv/caas/* ), Kubeconfig-Dateien werden nicht dauerhaft gespeichert.

<!-- page break -->

### 5.3 Knotenwartung: Neustart, Patch und Austausch (SOP-CAAS-01)

Dies ist der häufigste Eingriff mit Mandantenberührung und deshalb der wichtigste Ablauf dieses Handbuchs. Abbildung 2 zeigt ihn mit Freigaben und Auswirkung je Mandant.

<!-- image -->

[Description] Das Diagramm stellt die Standardarbeitsanweisung „SOP-CAAS-01 – Knotenwartung“ für Worker-Knoten in `ocp-prod` dar, unterteilt in die vier horizontalen Prozesszonen „Vorbereitung – Plattformbetrieb“, „Abstimmung – Mandanten“, „Durchführung – Plattformbetrieb“ und „Abschluss und Nachweis“ sowie eine tabellarische Übersicht der Mandantenauswirkungen. Zu den gezeigten Systemen, Werkzeugen und Komponenten gehören unter anderem OpenShift-Knoten und Pods (mit Befehlen wie `oc adm cordon`, `drain` und `uncordon`), PodDisruptionBudgets (PDB), Jira/CAASUP sowie Mandantendienste wie das Event-System 2.0 (Kafka), Mars Dokumentendienste, Vault, Prometheus, Loki und VPP. Beschriftete Pfeile (darunter „Ankündigung an alle Mandanten“, „Freigaben liegen vor“ und die Entscheidungszweige „ja/nein/geklärt“ bei blockierenden PDBs) verdeutlichen die sequenzielle Schrittabfolge, Phasenübergänge und Rückkopplungsschleifen zwischen dem Plattformbetrieb und den Mandanten.

Abbildung 2: SOP-CAAS-01 - Knotenwartung mit Abstimmung, Entleeren, Sonderfall PodDisruptionBudget und Nachweis. Die Tabelle im unteren Teil nennt je Mandant Arbeitslast, Besonderheit, Auswirkung und Ansprechpartner.

#### Vorgehen:

1. Change in CAASUP anlegen, Vorlauf 10 Arbeitstage, betroffene Knoten und Zeitraum nennen.
2. Arbeitslasten auf dem Knoten ermitteln und je Mandant die Auswirkung bestimmen:
3. Mandanten informieren und Rückmeldung abwarten. Ohne Zustimmung wird nicht entleert; Ausnahmen bei fristgebundenen Sicherheitspatches entscheidet die Bereichsleitung IT-B (Dr. Martina Kellerhoff), dann mit mindestens 24 Stunden Vorlauf.
4. Knoten sperren und entleeren:
5. Bleibt das Entleeren stehen, blockiert in der Regel ein PodDisruptionBudget. Betroffen ist typischerweise der Dispatcher des Event-Systems. Dann Kontakt zu Jonas Brinkmann: entweder wird die Replikazahl

```
oc get pods -A -o wide --field-selector spec.nodeName=<node> oc get poddisruptionbudget -A
```

```
oc adm cordon <node> oc adm drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=600s
```

<!-- page break -->

vorübergehend erhöht oder das Fenster verschoben. Ein Erzwingen mit --force ist nicht zulässig.

6. Wartung durchführen (Neustart, Patch, Austausch durch das ZRB).
7. Knoten freigeben und Verteilung prüfen:
8. Verifikation: Alarme leer, Speicherschicht gesund, Mandanten informieren, Change mit Nachweis abschließen.

```
oc adm uncordon <node> oc get nodes -o wide oc get pods -A -o wide | grep -c Running
```

#### Sonderfall Vault

Vor dem Entleeren eines Knotens ist zu prüfen, ob dort ein Vault-Pod läuft ( oc get pods -n vault-system -o wide ). Ist es der Führungsknoten, wird zuerst ein Wechsel abgewartet; fällt der Verbund unter zwei erreichbare Knoten, muss Marcel Ebert (ZSD) für das Entsiegeln bereitstehen. Solange Vault versiegelt ist, starten bei keinem Mandanten neue Pods (siehe Kapitel 6.2 und BHB-PLT-0007 ).

### 5.4 Clusterupdate (SOP-CAAS-02)

Updates der OpenShift-Version durchlaufen die Cluster aufwärts von ocp-di bis ocp-prod , mit mindestens fünf Arbeitstagen Abstand zwischen den Stufen. Der aktuelle Stand ist 4.16.21; der Wechsel auf 4.17 ist für das vierte Quartal 2026 geplant. Ablauf je Cluster:

1. Freigabehinweise des Herstellers auf entfernte Programmierschnittstellen prüfen und die Mandanten über betroffene Ressourcentypen informieren.
2. Vorabprüfung auf ocp-di , danach Rückmeldung der Mandanten aus ocp-dev und ocp-test abwarten - insbesondere die Regressionstests des Event-Systems und der Dokumentendienste.
3. Update der Steuerungsebene, danach der Worker in Gruppen von je drei Knoten; zwischen den Gruppen wird die Verteilung der Arbeitslasten geprüft.
4. Nach dem Update: Funktionstests der Mandanten, Freigabe durch den Produktverantwortlichen des jeweiligen Verfahrens.

Rückfall (Rollback). Ein Clusterupdate ist nach dem Update der Steuerungsebene nicht rückrollbar; ein Rollback der OpenShift-Version wird vom Hersteller nur zwischen zwei Patchständen derselben Nebenversion unterstützt und ist in SOP-CAAS-02 ausdrücklich ausgeschlossen. Der Rückfallweg besteht deshalb aus drei Stufen: Erstens wird die Aktualisierung der Worker angehalten ( oc adm upgrade pause in der Maschinenkonfiguration), solange nur ein Teil der Knoten gewechselt hat. Zweitens werden fehlerhafte Operatorversionen einzeln zurückgenommen - der Abonnementkanal wird auf den vorherigen Stand gesetzt und der Operator neu installiert. Drittens gilt für den Zustand des Clusters der etcd-Schnappschuss: Eine Wiederherstellung nach SOP-CAAS-06 stellt den Zustand vor dem Update wieder her, kostet aber nach Erfahrung aus der Wiederherstellungsübung vom 24.01.2026 rund zwei Stunden und verwirft alle Änderungen der Mandanten seit dem Schnappschuss. Anwendungen der Mandanten sind davon nicht betroffen, solange sie über GitOps beschrieben sind; deshalb ist der Releasewechsel eines Mandanten immer unabhängig vom Clusterupdate und wird über das Repository caas-tenants zurückgesetzt (Schwenk auf den vorherigen Commit, Wiederherstellung in weniger als zehn Minuten).

Operator-Updates, die ein Mandant benötigt - etwa OpenShift Serverless für das Event-System - werden vom Plattformbetrieb bereitgestellt, aber von dem Mandanten verantwortet und getestet. Der Wechsel auf Serverless 1.36 wurde am 30.06.2026 in ocp-test bereitgestellt; die dabei aufgetretene Störung des Dispatchers lag im Verantwortungsbereich des Mandanten (ESSUP-1602).

<!-- page break -->

### 5.5 Zertifikate der Plattform (SOP-CAAS-04)

Die Plattform bezieht ihre Zertifikate automatisiert aus der internen PKI; ausstellende Instanz ist die BAVD Issuing CA 3 unter der BAVD Root CA 2 (Rahmenkonzept PKI-RK-002 , Betrieb nach BHB-PLT-0007 ). certmanager 1.14.5 ist mit dem ClusterIssuer bavd-issuing-ca-3 gegen den ACME-Endpunkt https://pki.bavd.intern/acme/directory konfiguriert; die Erneuerung beginnt 30 Tage vor Ablauf. Betroffen sind die Zertifikate der Konsole, der API, des Ingress-Wildcards *.apps.prod.caas.bavd.intern und der Routen der Mandanten.

```
oc get clusterissuer bavd-issuing-ca-3 -o jsonpath='{.status.conditions}' oc get certificate -A | grep -v True cmctl renew ingress-wildcard -n openshift-ingress
```

Voraussetzung ist die Firewall-Regel FW-CAAS-004 . Fällt sie aus, bleibt die Erneuerung stillschweigend aus, bis ein Zertifikat abläuft - genau so entstand am 21.08.2025 der Ausfall der Recherche der Dokumentendienste (DDSUP-0794, Partnervorgang ZSDSUP-0119). Seither überwacht die Plattform den ACME-Pfad mit einer eigenen Prüfung (Alarm PkiAcmeProbeFailed , siehe Kapitel 8). Zertifikate, die nicht über cert-manager laufen - etwa die Keystores der Archiv-Adapter der Dokumentendienste oder die KafkaBroker-Zertifikate - verantworten die Mandanten selbst; das Verfahren steht in BHB-PLT-0007 .

### 5.6 Mandanten-Onboarding (SOP-CAAS-03)

Ein neuer Mandant erhält innerhalb von zehn Arbeitstagen: Namespaces je Stage, Ressourcenkontingent nach Kontingentklasse des Servicekatalogs, AD-Gruppe und Rolle, NetworkPolicy-Grundgerüst, Anbindung an ArgoCD, eine Route mit Zertifikatsautomatik, optional eine feste Egress-Adresse sowie Aufnahme in die Observability. Voraussetzung sind ein benannter Produktverantwortlicher, ein Betriebshandbuch in Arbeit und eine Schutzbedarfsfeststellung. Die Abnahme erfolgt mit einem Funktionstest des Mandanten.

### 5.7 Standard Operating Procedures und regelmäßige Tätigkeiten

Tabelle 9: Standard Operating Procedures

| SOP         | Titel                                       | Auslöser                                | Verantwortlich   |
|-------------|---------------------------------------------|-----------------------------------------|------------------|
| SOP-CAAS-01 | Knotenwartung und Entleeren                 | Neustart, Patch, Hardwaretausch         | Sonja Wiechert   |
| SOP-CAAS-02 | Clusterupdate                               | neue OpenShift-Version, Operator-Update | Andreas Wehrle   |
| SOP-CAAS-03 | Mandanten-Onboarding und Kontingentänderung | Antrag eines Verfahrens                 | Sonja Wiechert   |
| SOP-CAAS-04 | Zertifikate der Plattform                   | Alarm TLSCertExpirySoon , CA-Wechsel    | Ines Baumgart    |
| SOP-CAAS-05 | Speichererweiterung und Kapazität           | Belegung über 75 Prozent                | Malte Grothe     |
| SOP-CAAS-06 | Notfall-Kaltstart des Gesamtverbunds        | Totalausfall, Übung                     | Andreas Wehrle   |

Tabelle 10: Regelmäßige betriebliche Tätigkeiten

| Tätigkeit                                          | Turnus         | Verantwortlich   | Nachweis                    |
|----------------------------------------------------|----------------|------------------|-----------------------------|
| Clusterzustand, Alarme und Knotenauslastung prüfen | arbeitstäglich | Rufbereitschaft  | Eintrag im Betriebstagebuch |

<!-- page break -->

| Tätigkeit                                          | Turnus                  | Verantwortlich   | Nachweis                           |
|----------------------------------------------------|-------------------------|------------------|------------------------------------|
| Erfolg der etcd-Sicherung prüfen                   | arbeitstäglich          | Sonja Wiechert   | Prüfliste                          |
| Speicherbelegung und Wachstum je Mandant auswerten | monatlich               | Malte Grothe     | Kapazitätsbericht                  |
| Zertifikatsrestlaufzeiten prüfen                   | wöchentlich             | Ines Baumgart    | Grafana-Panel                      |
| Kontingentnutzung mit den Mandanten abstimmen      | quartalsweise           | Sonja Wiechert   | Protokoll der Mandantenrunde       |
| Wiederherstellung einer etcd-Sicherung üben        | halbjährlich            | Andreas Wehrle   | Übungsprotokoll                    |
| Kaltstartübung (Teil- oder Vollübung)              | halbjährlich / jährlich | Andreas Wehrle   | Übungsprotokoll, siehe Kapitel 6.4 |

<!-- page break -->

## 6 Abhängigkeiten und Auswirkungen

### 6.1 Wovon die Plattform abhängt

Abbildung 3 zeigt beide Richtungen: links die Vorleistungen, ohne die die Plattform nicht arbeitet, rechts die Mandanten, die von ihr abhängen - und rechts unten das VPP, das bewusst außerhalb steht.

<!-- image -->

[Description] Das Diagramm gliedert sich in eine linke Übersicht der Systemabhängigkeiten („Abhängigkeiten“) und eine rechte Tabelle mit der elfstufigen Kaltstartreihenfolge des Verbunds nach SOP-CAAS-06. Auf der linken Seite speisen infrastrukturelle Erbringer (ZRB, Netzbetrieb) und Sicherheitsdienste der Zone ZSD (PKI, IAM, Vault) die zentrale „CaaS-Plattform“ (OpenShift), welche ihrerseits verschiedene Mandantensysteme (Event-System 2.0, Mars Dokumentendienste, Observability, Neun Fachanwendungen) bereitstellt, während das System VPP plattformunabhängig bleibt. Pfeile und Beschriftungen verdeutlichen Kommunikations- und Protokollpfade (z. B. VMs/Netz, ACME 443, OIDC 443, Secrets 443 sowie Namespaces), wobei eine rote Linie die zirkuläre „Ringabhängigkeit“ zwischen Vault, PKI und der CaaS-Plattform hervorhebt.

Abbildung 3: Abhängigkeiten der Plattform und Kaltstartreihenfolge des Gesamtverbunds. Rot hervorgehoben die Ringabhängigkeit zwischen Vault, PKI und Plattform.

Tabelle 11: Vorleistungen und ihre Wirkung bei Ausfall

| Vorleistung                                 | Erbringer                   | Wirkung bei Ausfall                                                         | Überbrückung                                                            |
|---------------------------------------------|-----------------------------|-----------------------------------------------------------------------------|-------------------------------------------------------------------------|
| Virtualisierung, Speicher- und Netzhardware | ZRB ( LS-ZRB-2022-5210 )    | Knoten fallen aus; bei mehr als sechs Knoten ist die Kapazität unzureichend | Verteilung über zwei Brandabschnitte, Kapazitätsreserve von zwei Knoten |
| Firewall, VIPs, Egress                      | Netzbetrieb (Frank Dettmer) | Plattform nicht erreichbar oder Mandanten ohne Datenbankzugriff             | keine; Regeländerungen nur per Change mit Rückfallplan                  |
| PKI und ACME                                | ZSD (Sabine Wollmer)        | keine Erneuerung von Zertifikaten; kritisch ab 7 Tagen Restlaufzeit         | manuelle Ausstellung über das RA-Portal                                 |
| IAM (Keycloak)                              | ZSD (Kai Ostermann)         | keine Anmeldung an Konsole und API                                          | Break-Glass-Konto brk-caas-admin , bestehende Token bleiben gültig      |
| Vault                                       | ZSD (Marcel Ebert)          | neue Pods aller Mandanten starten nicht                                     | keine; laufende Pods sind nicht betroffen                               |

<!-- page break -->

| Vorleistung   | Erbringer          | Wirkung bei Ausfall                      | Überbrückung                                        |
|---------------|--------------------|------------------------------------------|-----------------------------------------------------|
| Nexus und Git | zentrale Werkzeuge | keine neuen Images, kein GitOps-Abgleich | Image-Cache der Knoten, laufender Betrieb unberührt |

### 6.2 Auswirkungen von Plattformereignissen auf die Mandanten

Tabelle 12 ist die Antwort auf die häufigste Frage der Mandanten: 'Was passiert bei uns, wenn ihr X macht?' Sie ist zugleich die Grundlage der Ankündigungen nach Kapitel 5.1.

Tabelle 12: Auswirkung von Plattformereignissen je Mandant

| Ereignis                          | Event-System 2.0                                                                            | Mars Dokumentendienste                                             | Observability                                 | VPP   |
|-----------------------------------|---------------------------------------------------------------------------------------------|--------------------------------------------------------------------|-----------------------------------------------|-------|
| Einzelnen Knoten entleeren        | Dispatcher wird einzeln verlagert, Zustellung bis 3 min verzögert                           | Ingest pausiert bis 2 min, Spool puffert                           | Messlücke bis 2 min                           | keine |
| Ingress-Router neu starten        | Broker-Ingress nicht erreichbar, Produzenten erhalten HTTP 503                              | Gateway nicht erreichbar, Recherche unterbrochen                   | Grafana nicht erreichbar                      | keine |
| API-Server neu starten            | laufende Zustellung unberührt, keine Konfigurationsänderung möglich                         | laufende Verarbeitung unberührt                                    | keine neuen Ziele erkannt                     | keine |
| Clusterupdate (Worker in Gruppen) | mehrfaches Verlagern, Zustellung verzögert, kein Verlust                                    | Ingest pausiert mehrfach, Lesezugriff verfügbar                    | Messlücken                                    | keine |
| Ausfall der Speicherschicht       | Dispatcher verliert seinen Zustand, Neuaufbau der Consumer-Gruppen nötig                    | Ingest-Spool nicht verfügbar, Annahme stoppt                       | keine neuen Messreihen                        | keine |
| Vault versiegelt                  | Neustart von Pods scheitert, laufender Betrieb unberührt                                    | dd-ingest-worker startet nicht                                     | Neustart scheitert                            | keine |
| Egress-Adresse nicht verfügbar    | keine (Kafka über eigene Regel)                                                             | kein Zugriff auf Oracle und Objektspeicher, Verarbeitung stoppt    | keine                                         | keine |
| Ausfall Brandabschnitt WE-B       | halbe Kapazität, keine Unterbrechung                                                        | halbe Kapazität, keine Unterbrechung                               | halbe Kapazität                               | keine |
| Ausfall Brandabschnitt WE-A       | halbe Kapazität; laufende Zustellung unberührt, kein Neustart und keine Verlagerung möglich | halbe Kapazität; laufende Verarbeitung unberührt, keine neuen Pods | halbe Kapazität, keine Konfigurationsänderung | keine |

#### Lesehilfe für Mandanten

Die Spalte VPP ist durchgehend leer - das ist beabsichtigt und der Grund, warum das VPP in diesem Handbuch als 'kein Mandant' geführt wird. Wer eine Anwendung entwerfen möchte, die Plattformwartungen unbemerkt übersteht, findet die notwendigen Bedingungen in Kapitel 5.3: Verteilung über beide Brandabschnitte, mindestens zwei Replikas, kein harter Zustand im Pod und ein PodDisruptionBudget, das eine Verlagerung zulässt.

### 6.3 Ringabhängigkeit Vault - PKI - Plattform

Vault läuft als Mandant auf dieser Plattform. Die Plattform bezieht ihre Zertifikate von der PKI. Die PKI wiederum hinterlegt Zugangsdaten und Schlüsselmaterial in Vault. Damit existiert ein Ring, der bei einem Kaltstart nicht aus sich heraus auflösbar wäre.

Aufgelöst wird er durch drei Festlegungen: IAM und PKI laufen auf eigenen virtuellen Maschinen im Hausnetz Süd und nicht auf dieser Plattform; die Plattform hält für den Kaltstart ein eigenes, langlaufendes Zertifikat für API und Konsole vor, das nicht über ACME erneuert wird; und das Entsiegeln von Vault erfolgt manuell mit drei von fünf Schlüsselanteilen. Die Halter der Anteile sind in BHB-PLT-0007 benannt - darunter der Teamleiter dieses Bereichs.

<!-- page break -->

### 6.4 Kaltstart des Gesamtverbunds (SOP-CAAS-06)

Tabelle 13 nennt die verbindliche Reihenfolge nach einem Totalausfall. Sie ist mit allen Beteiligten abgestimmt und wird jährlich geübt; die letzte gemeinsame Vollübung am 15.05.2026 dauerte 5 Stunden 20 Minuten; Schritt 7 (Vault entsiegelt) war nach 164 Minuten erreicht.

Tabelle 13: Kaltstartreihenfolge des Gesamtverbunds

|   Nr. | Schritt                                 | Verantwortlich      | Dauer   | Voraussetzung                       |
|-------|-----------------------------------------|---------------------|---------|-------------------------------------|
|     1 | Virtualisierung, Speicher, Netzhardware | ZRB                 | 60 min  | Strom und Kühlung                   |
|     2 | Firewall, Lastverteiler, VIPs           | Frank Dettmer       | 30 min  | Schritt 1                           |
|     3 | Active Directory und IAM                | Kai Ostermann       | 20 min  | Schritt 2                           |
|     4 | PKI: Issuing CA, OCSP, ACME             | Sabine Wollmer      | 15 min  | Schritt 3                           |
|     5 | Steuerungsebene und etcd der Plattform  | Sonja Wiechert      | 25 min  | Schritt 2, Kaltstartzertifikat      |
|     6 | Worker und Speicherschicht              | Malte Grothe        | 30 min  | Schritt 5                           |
|     7 | Vault entsiegeln (3 von 5 Anteilen)     | Marcel Ebert        | 15 min  | Schritt 6, drei Halter erreichbar   |
|     8 | Kafka-Cluster                           | Talwerk IT-Services | 20 min  | Schritt 2                           |
|     9 | Event-System 2.0                        | Tobias Reinhardt    | 20 min  | Schritte 7 und 8                    |
|    10 | Mars Dokumentendienste                  | Rainer Kolbe        | 40 min  | Schritt 7, Oracle verfügbar         |
|    11 | VPP                                     | Torben Machwitz     | 45 min  | Schritt 3; ab dort parallel möglich |

Gesamtdauer bis zur vollständigen Wiederaufnahme: rund fünf Stunden. Ab vier Stunden Ausfall wird der Krisenstab nach NFH-ITB-2.1 einberufen. Abweichungen im Übungsverlauf werden als Vorgang in CAASUP erfasst und im Betriebsbericht ausgewertet.

<!-- page break -->

## 7 Troubleshooting

### 7.1 Erste Prüfungen

Bei jeder Meldung eines Mandanten sind zuerst diese Fragen zu klären, damit die Störung richtig zugeordnet wird:

1. Ist die Plattform betroffen oder die Anwendung?
2. Läuft es nur bei einem Mandanten schief? Dann liegt die Ursache mit hoher Wahrscheinlichkeit im Namespace des Mandanten - Kontingent, Image, Konfiguration.
3. Ist Vault erreichbar und entsiegelt?
4. Sind Zertifikate aktuell? oc get certificate -A | grep -v True
5. Ist der Speicher gesund? Speicherkonsole, Alarme OdfCapacityHigh und CephClusterDegraded .

```
oc get nodes oc get co oc get events -A --sort-by=.lastTimestamp | tail -30
```

```
oc -n vault-system exec vault-0 -- vault status | grep -E "Sealed|HA Mode"
```

### 7.2 Entleeren eines Knotens bleibt stehen

#### Umgebung

Produktion, ocp-prod , während einer geplanten Wartung.

#### Fehlerbeschreibung

oc adm drain läuft in das Zeitlimit, ohne alle Pods zu verlagern:

```
evicting pod eventing-kafka-broker/kafka-broker-dispatcher-1 error when evicting pods/"kafka-broker-dispatcher-1" -n "eventing-kafka-broker" Cannot evict pod as it would violate the pod's disruption budget.
```

#### Lösung

Kein --force . Mandanten kontaktieren (Jonas Brinkmann, Event-System) und entweder die Replikazahl vorübergehend von drei auf vier erhöhen oder die Wartung auf das nächste Fenster verschieben. Nach der Wartung wird die ursprüngliche Replikazahl wiederhergestellt.

#### Hauptursache

Das PodDisruptionBudget minAvailable=2 des StatefulSets lässt bei drei Replikas nur eine gleichzeitige Störung zu. Werden zwei Knoten parallel entleert, blockiert die zweite Verlagerung zwangsläufig.

#### Schritte zur Nachbildung

In ocp-test zwei Knoten mit Dispatcher-Pods gleichzeitig entleeren.

### 7.3 Vault nach Knotenwartung versiegelt (CAASUP-0351)

#### Umgebung

Produktion, 02.07.2026 ab 05:40 Uhr, kurzfristig genehmigte Knotenwartung außerhalb des regulären Fensters; Partnervorgang ZSDSUP-0247 .

<!-- page break -->

#### Fehlerbeschreibung

Beim Entleeren zweier Knoten wurden zwei der drei Vault-Pods verlagert; sie starteten versiegelt, und mit nur einem entsiegelten Knoten verlor der Raft-Verbund sein Quorum. Anschließend blieben Pods mehrerer Mandanten im Zustand Init:0/1 :

```
Warning  FailedMount  4s  kubelet MountVolume.SetUp failed for volume "vault-secret": secrets "dd-db-meta" not found (vault-agent: server is sealed)
```

#### Lösung

Marcel Ebert (ZSD) entsiegelte mit drei von fünf Schlüsselanteilen; danach starteten die Pods selbstständig. Gesamtdauer 48 Minuten, davon 31 Minuten Wartezeit auf die Halter der Anteile.

#### Hauptursache

Die Wartung berücksichtigte den Vault-Verbund nicht. Seither ist die Prüfung auf Vault-Pods verbindlicher Schritt in SOP-CAAS-01, und bei Arbeiten an Knoten mit Vault-Pods wird die Rufbereitschaft des ZSD vorab eingeplant.

#### Schritte zur Nachbildung

In ocp-test zwei der drei Vault-Pods gleichzeitig beenden.

### 7.4 Ingress-Wartung ohne Ankündigung (CAASUP-0342)

#### Umgebung

Produktion, 24.06.2026, außerhalb des Wartungsfensters; Partnervorgang ESSUP-1588 .

#### Fehlerbeschreibung

Nach einem Neustart der Router-Pods war der Broker-Ingress des Event-Systems elf Minuten nicht erreichbar. Produzenten erhielten HTTP 503; die Ereignisse mussten von den Fachanwendungen gepuffert und erneut gesendet werden.

#### Lösung

Der Neustart lief planmäßig durch; die Erreichbarkeit stellte sich nach elf Minuten selbst wieder her. Der eigentliche Fehler war organisatorisch: keine Ankündigung.

#### Hauptursache

Der Change war als 'ohne Mandantenauswirkung' eingestuft. Seither gilt jeder Eingriff an Ingress, API oder Knoten als mandantenrelevant (Kapitel 5.1).

#### Schritte zur Nachbildung

In ocp-test oc -n openshift-ingress rollout restart deploy/router-default ausführen und parallel den funktionalen Test des Event-Systems laufen lassen.

### 7.5 Kontingent des Mandanten erschöpft (CAASUP-0338)

#### Umgebung

Produktion, 17.06.2026; Partnervorgang DDSUP-1195 .

#### Fehlerbeschreibung

Pods des OCR-Dienstes der Dokumentendienste wurden während der Aufbereitung großer Sammelakten beendet:

```
State: Terminated   Reason: OOMKilled   Exit Code: 137 Last State: Running  Container: dd-ocr-service
```

<!-- page break -->

Das Speicherlimit des Dienstes war zu niedrig für die auslösende Sammelakte mit 1 284 Seiten; der Mandant verarbeitet Dokumente über 150 Seiten oder 100 MB seither grundsätzlich blockweise (siehe BHB-VRF-0118 , Kapitel 6.3.5). Nach Abstimmung wurde das Kontingent des Mandanten auf 24 vCPU / 48 GiB erhöht und das Limit des Dienstes vom Mandanten angepasst.

#### Hauptursache

Kontingente sind harte Grenzen; die Plattform beendet Pods ohne Vorwarnung. Die Verantwortung für die Bemessung liegt beim Mandanten, die Plattform liefert die Auslastungsdaten.

#### Schritte zur Nachbildung

Speicherlimit eines Testdienstes auf 256 MiB setzen und ein großes Dokument aufbereiten lassen.

### 7.6 Incident-Liste

Tabelle 14: Incidents mit Mandantenauswirkung (Auszug)

| Vorgang     | Datum      | Titel                                  | Ursache                                            | Dauer   | Maßnahme und Partnervorgang                           |
|-------------|------------|----------------------------------------|----------------------------------------------------|---------|-------------------------------------------------------|
| CAASUP-0198 | 14.11.2025 | Speicherbelegung über 85 Prozent       | Aufbewahrung der Mandanten-Volumes nicht überwacht | 3:20    | Alarm ab 75 Prozent, Kapazitätsbericht je Mandant     |
| CAASUP-0287 | 09.03.2026 | etcd-Latenz nach Speicherwartung       | Wartung des ZRB ohne Ankündigung                   | 1:05    | Abstimmungspflicht im Leistungsschein ergänzt         |
| CAASUP-0338 | 17.06.2026 | OCR-Pods der Dokumentendienste beendet | Kontingent erschöpft                               | 2:10    | Kontingent erhöht · DDSUP-1195                        |
| CAASUP-0342 | 24.06.2026 | Ingress-Wartung ohne Ankündigung       | Change falsch eingestuft                           | 0:11    | Abstimmung 10 Arbeitstage verbindlich · ESSUP-1588    |
| CAASUP-0351 | 02.07.2026 | Vault nach Knotenwartung versiegelt    | Vault-Verbund bei der Wartung nicht berücksichtigt | 0:48    | Prüfschritt in SOP-CAAS-01 · ZSDSUP-0247 , DDSUP-1201 |

<!-- page break -->

## 8 Monitoring, Sicherung und Notfall

### 8.1 Überwachung

Die Plattform überwacht sich mit dem Observability-Stack im Namespace obs-stack ; die Mandanten nutzen dieselbe Datenbasis für ihre eigenen Dashboards. Tabelle 15 nennt die Kennzahlen mit Mandantenrelevanz.

Tabelle 15: Überwachte Kennzahlen und Alarme

| Kennzahl                          | Schwellwert        | Alarm                | Erste Maßnahme                                 |
|-----------------------------------|--------------------|----------------------|------------------------------------------------|
| Nicht bereite Knoten              | > 0 über 5 min     | NodeNotReady         | Knoten prüfen, ZRB einbeziehen                 |
| etcd-Schreiblatenz (p99)          | > 100 ms           | EtcdHighLatency      | Speicherlast prüfen, ZRB einbeziehen           |
| Speicherbelegung                  | > 75 %             | OdfCapacityHigh      | SOP-CAAS-05, Erweiterung planen                |
| Zustand der Speicherschicht       | nicht HEALTH_OK    | CephClusterDegraded  | Speicherkonsole, betroffene Datenträger prüfen |
| Kontingentnutzung je Mandant      | > 90 %             | TenantQuotaNearLimit | Mandanten informieren (Lehre aus CAASUP-0338)  |
| Restlaufzeit Plattformzertifikate | < 30 / 14 / 7 Tage | TLSCertExpirySoon    | SOP-CAAS-04                                    |
| ACME-Prüfung                      | fehlgeschlagen     | PkiAcmeProbeFailed   | Regel FW-CAAS-004 und PKI prüfen               |
| Vault-Zustand                     | versiegelt         | VaultSealed          | ZSD alarmieren (Marcel Ebert)                  |
| Pod-Neustarts                     | > 5 in 15 min      | PodFlapping          | Mandanten informieren, Ursache im Namespace    |

### 8.2 Sicherung und Wiederherstellung

Tabelle 16: Sicherungsobjekte

| Objekt                    | Verfahren                                   | Turnus             | Aufbewahrung       |
|---------------------------|---------------------------------------------|--------------------|--------------------|
| Clusterzustand (etcd)     | Sicherungspunkt, Auslagerung nach Commvault | alle 6 Stunden     | 14 Tage            |
| Clusterkonfiguration      | Git ( caas-infra ), GitOps                  | bei jeder Änderung | unbegrenzt         |
| Mandanten-Volumes         | Snapshots der Speicherschicht               | täglich            | 7 Tage             |
| Geheimnisse der Plattform | Vault (Verantwortung ZSD)                   | laufend            | siehe BHB-PLT-0007 |

Die Wiederherstellung eines Clusters erfolgt nicht durch Zurückspielen von Daten, sondern durch Neuaufbau aus Git und, falls nötig, durch Wiederherstellung des etcd-Sicherungspunkts. Zielzeit sind zwei Stunden (RTO). Für die über GitOps beschriebene Konfiguration ist der Datenverlust null (RPO 0), weil Git die führende Quelle ist; für den nicht in Git abgebildeten Clusterzustand (etcd, etwa ausgestellte Zertifikate und Ereignisse) beträgt der Rückstand höchstens sechs Stunden. Wichtig für Mandanten: Die Plattform sichert keine Anwendungsdaten - Datenbanken, Objektspeicher und Archive verantworten die Verfahren selbst.

### 8.3 Notfall

Bei einem Vollausfall der Produktion über eine Stunde: Störung mit Schweregrad 1 in CAASUP , Ankündigung im Kanal #caas-plattform , Information aller Mandanten-Produktverantwortlichen sowie der Bereichsleitung IT-B. Ab vier Stunden Krisenstab nach NFH-ITB-2.1 . Für den Wiederanlauf gilt die Reihenfolge aus Tabelle 13; die Mandanten starten erst nach Freigabe durch den Plattformbetrieb, damit nicht mehrere Verfahren gleichzeitig auf einen halb verfügbaren Cluster zugreifen.

<!-- page break -->

## 9 Rollen, Verantwortlichkeiten und Eskalation

### 9.1 Rollen

Tabelle 17: Rollen und Verantwortlichkeiten

| Rolle                                | Person                                            | Umfang                                                                  |
|--------------------------------------|---------------------------------------------------|-------------------------------------------------------------------------|
| Teamleitung und Produktverantwortung | Andreas Wehrle (Durchwahl 2140)                   | Gesamtverantwortung, Clusterupdates, Mandantenvereinbarungen, Kaltstart |
| Vertretung, Clusterbetrieb           | Sonja Wiechert (Durchwahl 2143)                   | Knotenwartung, Onboarding, Kontingente, Changes                         |
| Speicher                             | Malte Grothe                                      | Speicherschicht, Speicherklassen, Kapazität, Snapshots                  |
| Ingress, Egress, Netz                | Ines Baumgart                                     | Routen, Zertifikatsautomatik, Abstimmung mit dem Netzbetrieb            |
| Bereichsleitung                      | Dr. Martina Kellerhoff                            | Eskalationsstufe 2, Ausnahmeentscheidungen bei fristgebundenen Patches  |
| Sicherheitsdienste                   | Kai Ostermann, Sabine Wollmer, Marcel Ebert (ZSD) | IAM, PKI, Vault - siehe BHB-PLT-0007                                    |
| Netzbetrieb                          | Frank Dettmer                                     | Firewall, VIPs, Zonenübergänge                                          |
| Infrastruktur                        | ZRB                                               | virtuelle Maschinen, Speicher- und Netzhardware                         |

### 9.2 Aufgabenteilung mit den Mandanten

- Plattform: Knoten, Speicher, Ingress, Egress, Service Mesh, Kontingente, Rollen, Plattformzertifikate, GitOps-Werkzeug.
- Mandant: Anwendungen, Images, Ressourcenbemessung innerhalb des Kontingents, eigene Zertifikate außerhalb der Routen, eigene Datenhaltung und Sicherung, eigenes Betriebshandbuch.
- Gemeinsam: Wartungsplanung, Kapazitätsplanung, Störungsabgrenzung, Updates von Operatoren, die ein Mandant benötigt.

### 9.3 Eskalationsweg

Tabelle 18: Eskalationsstufen

|   Stufe | Auslöser                                                          | Adressat                                                         | Frist            |
|---------|-------------------------------------------------------------------|------------------------------------------------------------------|------------------|
|       1 | Störung nicht angenommen oder Lösungsweg unklar                   | Andreas Wehrle, Vertretung Sonja Wiechert                        | sofort           |
|       2 | mehr als ein Mandant betroffen, Ausfall über eine Stunde          | Bereichsleitung IT-B (Dr. Martina Kellerhoff)                    | innerhalb 30 min |
|       3 | Totalausfall über vier Stunden oder Verdacht auf Kompromittierung | Krisenstab nach NFH-ITB-2.1 , Informationssicherheitsbeauftragte | unverzüglich     |

<!-- page break -->

## 10 Glossar und weiterführende Dokumente

### 10.1 Glossar

#### Brandabschnitt

baulich getrennter Bereich des Rechenzentrums. Die Produktion verteilt sich auf WE-A und WE-B.

#### cert-manager

Komponente, die Zertifikate automatisch bei der internen PKI beantragt und erneuert.

#### ClusterIssuer

clusterweite Konfiguration, die festlegt, welche Zertifizierungsstelle cert-manager verwendet - hier bavd-issuing-ca-3 .

#### Egress-Adresse

feste Quelladresse, mit der Verkehr die Plattform verlässt; Voraussetzung für Firewall-Freischaltungen der Mandanten.

#### etcd

verteilter Speicher für den Zustand des Clusters. Verliert er sein Quorum, ist keine Änderung mehr möglich.

#### Entleeren (drain)

geordnetes Verlagern aller Pods von einem Knoten vor einer Wartung.

#### GitOps

Betriebsmodell, bei dem der gewünschte Zustand vollständig in Git beschrieben und automatisch abgeglichen wird.

#### Ingress

Eingangspunkt für Verkehr aus dem Behördennetz, hier über den VIP 10.30.8.7 .

#### Kontingent (Quota)

harte Obergrenze für CPU, Arbeitsspeicher und Objekte eines Mandanten.

#### Mandant

Team, das eigene Anwendungen auf der Plattform betreibt und dafür Namespaces, Kontingent und Rollen erhält.

#### Namespace

logische Trennung innerhalb eines Clusters; Grenze der Rechte eines Mandanten.

#### OpenShift Data Foundation

Speicherschicht auf Ceph-Basis, die Block-, Datei- und Objektspeicher bereitstellt.

#### PodDisruptionBudget

Regel eines Mandanten, wie viele Instanzen einer Arbeitslast gleichzeitig ausfallen dürfen. Blockiert bewusst das Entleeren.

#### Service Mesh

Zwischenschicht, die den Verkehr zwischen Arbeitslasten mit gegenseitiger TLS-Authentifizierung absichert.

#### Speicherklasse

Vorlage, die Art und Eigenschaften eines persistenten Volumes festlegt (RWO, RWX, Objekt).

#### Vault

Dienst zur Verwaltung von Geheimnissen, betrieben vom ZSD, aber als Mandant auf dieser Plattform.

#### Versiegelt (sealed)

Zustand von Vault, in dem keine Geheimnisse ausgegeben werden. Neue Pods der Mandanten starten dann nicht.

### 10.2 Weiterführende Dokumente

Tabelle 19: Weiterführende Dokumente und Seiten

| Titel   | Ort oder Kennung   | Inhalt   |
|---------|--------------------|----------|

<!-- page break -->

| Titel                                        | Ort oder Kennung                                          | Inhalt                                                            |
|----------------------------------------------|-----------------------------------------------------------|-------------------------------------------------------------------|
| Standard Operating Procedures                | confluence.bavd.intern/display/CAAS/SOP                   | vollständige Anweisungen SOP-CAAS-01 bis 06                       |
| Wartungskalender                             | confluence.bavd.intern/display/CAAS/Wartungskalender      | Fenster der Plattform und aller Mandanten                         |
| Mandantenliste                               | confluence.bavd.intern/display/CAAS/Mandanten             | alle 13 Mandanten mit Namespaces, Kontingent und Ansprechpartnern |
| Betriebshandbuch Zentrale Sicherheitsdienste | BHB-PLT-0007                                              | IAM, PKI, Vault; Auswirkungen bei Neustart und Ausfall            |
| Betriebshandbuch Event-System 2.0            | BHB-PLT-0042                                              | Mandant, Zustellgarantien, Observability-Stack                    |
| Betriebshandbuch Mars Dokumentendienste      | BHB-VRF-0118                                              | Mandant, Ingest-Spool, Egress-Nutzung                             |
| Betriebshandbuch VPP                         | BHB-VRF-0207                                              | Verfahren ohne Plattformbezug, gemeinsame Basisdienste            |
| Repositories                                 | git.bavd.intern → caas-infra, caas-tenants, caas-policies | Clusterkonfiguration, Mandantendefinitionen, Netzwerkregeln       |