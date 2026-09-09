BETRIEBSHANDBUCH

## Event-System 2.0

Zentrale Plattformkomponente für eventgetriebene Anwendungen in der Cloud des Bundesamtes für Verfahrensdienste

| Anwendung        | Event-System 2.0                                  |
|------------------|---------------------------------------------------|
| CI-Nummer        | CI-PLT-0042                                       |
| Verantwortlicher | Tobias Reinhardt (Bereich IT-B 2, Durchwahl 2117) |
| Vertretung       | Nadine Schäfer (Durchwahl 2119)                   |
| Fachseite        | Bereich IT-B 2 - Plattformdienste                 |
| Dokument         | BHB-PLT-0042, Version 2.4                         |
| Stand            | 24. Juli 2026                                     |
| Klassifizierung  | intern · Testdokument - fiktive Daten             |

Herausgeber: Bundesamt für Verfahrensdienste (BAVD), Bereich IT-B 2 - Plattformdienste · Interne Dokumentation · Weitergabe nur an berechtigte Stellen

<!-- page break -->

## Inhaltsverzeichnis

## 1 Dokumentinformation

### Zweck und Geltungsbereich
### Zielgruppe
### Änderungshistorie
### Verwandte Dokumente

## 2 Kurzbeschreibung

### Fachlicher Zweck
### Abgrenzung
### Kennzahlen des laufenden Betriebs

## 3 Planerische Anforderungen an die Struktur

### Verfügbarkeit
### Dimensionierung
### Schutzbedarf
### Anbindung an andere Schnittstellen und Basisdienste
### Weitere Anforderungen

Umgebungen und Stages

Update- und Releasezyklus

### Ticketsystem
### Direktkontakt

## 4 Systemüberblick

### Fachlicher Überblick
### Kontextdiagramm
### Schnittstellen
### Serverinstanzen
### Storage
### Anwendungen und Dienste
### Systemdiagramm
### Vernetzung
### Paket- und Versionsübersicht
### Ablauf der Eventzustellung

## 5 Administration

### Servicezeiten und Wartungsfenster
### Zugänge und Nutzerverwaltung

Umgang mit Geheimnissen

### Aufnahme und Unterbrechung des Betriebs

Erstmalige Aufnahme des Betriebes Geordnetes Stoppen und Starten

### Installation und Release-/Updatewechsel
### Standard Operating Procedures
### Regelmäßige betriebliche Tätigkeiten
### Skripte und Automatisierung

<!-- page break -->

### 5.8 Zertifikatsverwaltung - TLS-Zertifikat erneuern

Gemeinsame Rahmenbedingungen

Weg A - Routen und Service Mesh (automatisiert)

Weg B - Kafka-Verbindung (manuell)

## 6 Troubleshooting

### First-Level-Support und Meldewege
### Vorgehen bei Störungen
### Dokumentierte Störungsbilder
### Consumer-Lag steigt, Zustellung verzögert sich
### SSLHandshakeException nach Wechsel der ausstellenden CA
### Trigger stellt nicht zu, Filter greift nicht
### Dead-Letter-Topic füllt sich nach Umzug eines Konsumenten
### Dispatcher startet nach einem Update nicht (CrashLoopBackOff)
### Incident-Liste
### Weitere Hinweise

## 7 Logging und Monitoring

### Aufbau der Überwachung
### Metriken und Schwellwerte
### Protokolle
### Tracing mit Tempo

## 8 Datensicherung, Wiederherstellung und Notfallplan

### Grundsatz
### Wiederherstellung
### Disaster Recovery
### Notfallplan
### Nachweise und Übungen

## 9 Testfälle

### Testarten
### Konkrete Testfälle

## 10 Rollen und Verantwortlichkeiten

### Rollenübersicht
### Supportlevel
### Dienstleister
### Eskalationsweg
### RACI-Matrix

## 11 Lizenzen und Verträge

### Lizenzverwaltung
### Verträge und Leistungsscheine
### Offene Punkte

## 12 Glossar und weiterführende Dokumente

### Glossar
### Weiterführende Dokumente und Seiten

<!-- page break -->

## 1 Dokumentinformation

### 1.1 Zweck und Geltungsbereich

Dieses Betriebshandbuch beschreibt den technischen Betrieb des Event-System 2.0 ( CI-PLT-0042 ), der zentralen Plattformkomponente für eventgetriebene Anwendungen in der Cloud des Bundesamtes für Verfahrensdienste (BAVD). Es dokumentiert Aufbau, Schnittstellen, Betriebsabläufe, Störungsbilder, Überwachung und Wiederherstellungsverfahren. Das Handbuch ist die verbindliche Betriebsgrundlage des Teams Plattformdienste; jeder wiederkehrende Handgriff ist hier beschrieben oder über eine der SOPs SOP-1 bis SOP-7 (Kapitel 5.5) erreichbar.

Der Geltungsbereich umfasst die Namespaces knative-eventing , eventing-kafka-broker , event-systemops und event-system-debug auf den vier Clustern der Container-Plattform als Dienst (CaaS), die zugehörige Konfiguration in den Repositories es-ocp-infra und es-config sowie die Nutzung der ApacheKafka-Instanzen im Hausnetz Süd. Nicht im Geltungsbereich: der Betrieb der Container-Plattform selbst (Team CaaS-Plattformbetrieb, Andreas Wehrle), der Betrieb der Kafka-Broker (Talwerk IT-Services GmbH), die Fachlogik der angebundenen Verfahren und die Inhalte der übertragenen Ereignisse.

### 1.2 Zielgruppe

- Team Plattformdienste (Bereich IT-B 2) - Hauptadressat aller Handlungsanweisungen, 1st und 3rd Level für das Event-System.
- Bedarfsträger, also die Projekte und Verfahren, die Ereignisse veröffentlichen oder beziehen - vor allem Kapitel 3.5, 4.3, 4.10 und 6.1.
- CaaS-Plattformbetrieb (Andreas Wehrle) - Schnittstelle zu Cluster, Service Mesh und Ingress.
- Talwerk IT-Services GmbH (Holger Pietsch) - Betrieb der Kafka-Broker, 3rd Level für Kafka.
- Beteiligte Fachstellen: Netzbetrieb (Frank Dettmer), PKI (Sabine Wollmer), IAM (Kai Ostermann).

### 1.3 Änderungshistorie

Tabelle 1 hält die Fortschreibung dieses Handbuchs fest. Die Pflege liegt beim Produktverantwortlichen; jede Änderung an Architektur, Portfreischaltungen oder Betriebsabläufen ist innerhalb von zehn Arbeitstagen nachzutragen.

Tabelle 1: Änderungshistorie dieses Betriebshandbuchs

|   Version | Datum      | Autor            | Änderung                                                                  |
|-----------|------------|------------------|---------------------------------------------------------------------------|
|       1.0 | 14.03.2024 | Tobias Reinhardt | Erstfassung zur Produktivsetzung des Event-System 2.0                     |
|       1.4 | 22.11.2024 | Jonas Brinkmann  | Kafka-Broker von ZooKeeper auf KRaft umgestellt, Dimensionierung ergänzt  |
|       2.0 | 17.04.2025 | Tobias Reinhardt | Gliederung an die Handbuchvorlage angepasst, RACI-Matrix aufgenommen      |
|       2.1 | 03.09.2025 | Miriam Falk      | Observability-Kapitel auf Tempo und Loki umgestellt, Alerts dokumentiert  |
|       2.2 | 28.01.2026 | Nadine Schäfer   | Anbindung der Mars Dokumentendienste (Broker dd-prod-broker ) aufgenommen |

<!-- page break -->

|   Version | Datum      | Autor            | Änderung                                                                             |
|-----------|------------|------------------|--------------------------------------------------------------------------------------|
|       2.3 | 19.05.2026 | Jonas Brinkmann  | Störungsbild zum Truststore nach CA-Wechsel ergänzt (ESSUP-1517), SOP-6 überarbeitet |
|       2.4 | 24.07.2026 | Tobias Reinhardt | Aktualisierung auf OpenShift Serverless 1.36, Kapitel 4.10 und 8.2 neu gefasst       |

### 1.4 Verwandte Dokumente

Tabelle 2 nennt die Dokumente, ohne die einzelne Kapitel dieses Handbuchs nicht vollständig sind. Die erweiterte Liste steht in Kapitel 12.2.

Tabelle 2: Unmittelbar verwandte Dokumente

| Dokument                                     | Kennung      | Bezug                                                                                                                                                                           |
|----------------------------------------------|--------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Betriebshandbuch Mars Dokumentendienste      | BHB-VRF-0118 | Bedarfsträger mit Broker dd-prod-broker und Trigger dd-archiv-events                                                                                                            |
| Betriebshandbuch CaaS-Plattform              | BHB-PLT-0001 | Cluster, Ingress, Service Mesh, Speicherklassen, Wartungsfenster der Plattform; Mandant event-system mit den Namespaces nach Kapitel 4.2                                        |
| Betriebshandbuch Zentrale Sicherheitsdienste | BHB-PLT-0007 | Anmeldung (Client es-grafana ), interne PKI und ACME, Truststore-Verteilung beim CA-Wechsel (Vorbedingung in SOP-6 ), SASL/SCRAM-Zugangsdaten unter kv/event-system/kafka/scram |
| Servicekatalog Plattformdienste              | SK-PLT-1.9   | Leistungsumfang, Onboarding von Bedarfsträgern, Abgrenzung der Zuständigkeiten                                                                                                  |
| Rahmenkonzept interne PKI                    | PKI-RK-002   | BAVD Root CA 2, Issuing CA 3, Antragsweg - Grundlage für Kapitel 5.8                                                                                                            |
| Zonenkonzept und Event-System                | NET-ZK-007   | Zonenübergang Metro-Region West ⇄ Hausnetz Süd (Kapitel 4.8)                                                                                                                    |
| Schutzbedarfsfeststellung Plattformdienste   | SBF-PLT-2025 | Grundlage für Kapitel 3.3                                                                                                                                                       |
| Notfallhandbuch Bereich IT-B                 | NFH-ITB-2.1  | Meldewege und Krisenstab, Grundlage für Kapitel 8.4                                                                                                                             |

#### Hinweis zur Dokumentenlenkung

Die gültige Fassung liegt im Confluence-Bereich des Teams Plattformdienste

( https://confluence.bavd.intern/display/PLT/Betriebshandbuch ). Ausdrucke sind unkontrollierte Kopien. Alle in diesem Handbuch genannten Personen, Hostnamen, IP-Adressen, Vorgangs- und Vertragsnummern sind Beispieldaten einer Erprobungsumgebung.

<!-- page break -->

## 2 Kurzbeschreibung

### 2.1 Fachlicher Zweck

Das Event-System 2.0 ist eine zentrale Plattformkomponente innerhalb der Cloud des Bundesamtes für Verfahrensdienste (BAVD). Es unterstützt Projekte bei der Realisierung eventgetriebener Anwendungen: Fachanwendungen veröffentlichen Ereignisse ('Events'), andere Anwendungen abonnieren sie und werden über Zustandsänderungen benachrichtigt, ohne dass die beteiligten Systeme einander kennen oder gleichzeitig verfügbar sein müssen. Das Event-System stellt dafür die Annahme, die Zwischenspeicherung, die Filterung und die Zustellung der Ereignisse innerhalb definierter Garantien bereit (Kapitel 4.10).

Die Konfiguration ist projektspezifisch: Jeder Bedarfsträger erhält einen eigenen Broker, legt eigene Ereignistypen fest und definiert über Trigger, welche Ereignisse an welche Zieladresse zugestellt werden. Die Konfiguration wird deklarativ in Git gepflegt und automatisiert ausgerollt (Kapitel 5.4).

### 2.2 Abgrenzung

Nicht Bestandteil des Event-System sind:

- Fachliche Inhalte. Ereignisse tragen ausschließlich Metadaten und Referenzen, niemals Fachdaten. Ein Konsument löst die Referenz beim fachlich zuständigen System auf; dort greift dessen Berechtigungsprüfung. Diese Festlegung ist die Grundlage der Schutzbedarfseinstufung in Kapitel 3.3.
- Fachlogik und Orchestrierung. Das Event-System entscheidet nicht, ob ein Ereignis fachlich zulässig ist, und führt keine Abläufe aus. Es filtert ausschließlich anhand der Attribute des Ereignisses.
- Betrieb der Kafka-Broker. Die Persistenz liegt auf Apache-Kafka-Instanzen im Hausnetz Süd, die von der Talwerk IT-Services GmbH betrieben werden (Vertrag RV-2024-0817 ).
- Betrieb der Container-Plattform. Cluster, Knoten, Ingress und Service Mesh verantwortet das Team CaaS-Plattformbetrieb.
- Langfristige Archivierung von Ereignissen. Die Aufbewahrung endet nach sieben Tagen (Kapitel 4.5). Wer Ereignisse revisionssicher aufbewahren muss, tut dies im eigenen Verfahren.

### 2.3 Kennzahlen des laufenden Betriebs

Tabelle 3 gibt den Betriebsumfang zum Stichtag 30.06.2026 wieder. Die Werte werden monatlich aus dem Ops-Cockpit (Kapitel 7.1) entnommen und im Betriebsbericht fortgeschrieben.

Tabelle 3: Betriebskennzahlen der Produktionsumgebung (Stand 30.06.2026)

| Kennzahl                   | Wert                   | Anmerkung                                         |
|----------------------------|------------------------|---------------------------------------------------|
| Angebundene Bedarfsträger  | 17                     | Projekte und Verfahren mit eigenem Broker         |
| Broker                     | 38                     | über alle vier Stages, davon 17 in Produktion     |
| Trigger                    | 112                    | davon 54 in Produktion                            |
| Kafka-Topics / Partitionen | 96 / 288               | Topic-Schema knative-broker-<namespace>- <broker> |
| Ereignisse je Werktag      | ca. 2,4 Mio.           | Mittelwert Juni 2026, Spitzentag 3,1 Mio.         |
| Durchsatz                  | 180 Ereignisse/s (p95) | Tagesspitze 640 Ereignisse/s, montags 07:00-09:00 |

<!-- page break -->

| Kennzahl                        | Wert            | Anmerkung                                    |
|---------------------------------|-----------------|----------------------------------------------|
| Zustelldauer Dispatcher → Sink  | 142 ms (p95)    | Schwellwert 500 ms, siehe Kapitel 7.2        |
| Fehlerhafte Zustellungen        | 0,04 %          | überwiegend HTTP 503 beim Konsumenten        |
| Ereignisse im Dead-Letter-Topic | 312 (Juni 2026) | vollständig aufgearbeitet, siehe Kapitel 6.2 |
| Verfügbarkeit                   | 99,97 %         | Messzeitraum April 2025 bis März 2026        |

#### Gut zu wissen

Das Event-System ist für die angebundenen Verfahren eine Infrastrukturkomponente: Fällt es aus, bleiben die Fachanwendungen bedienbar, die Benachrichtigung anderer Systeme verzögert sich aber. Produzenten müssen deshalb in der Lage sein, Ereignisse zu puffern und später erneut zu senden - diese Anforderung ist Teil des Onboardings (SOP-5).

<!-- page break -->

## 3 Planerische Anforderungen an die Struktur

### 3.1 Verfügbarkeit

Für die Produktionsumgebung gilt eine Zielverfügbarkeit von 99,9 % innerhalb der Betriebszeit. Im Messzeitraum April 2025 bis März 2026 wurden 99,97 % erreicht. Gemessen wird nicht die Erreichbarkeit einzelner Pods, sondern die Ende-zu-Ende-Zustellung: Der Dienst chronsource erzeugt jede Minute ein Heartbeat-Ereignis, das über einen Broker und einen Trigger an den ce-metrics-collector zugestellt wird. Bleibt die Zustellung aus, zählt die Minute als Ausfallminute (Metrik heartbeat_missing_total , Kapitel 7.2).

Tabelle 4 fasst die Kennwerte zusammen. Geplante Wartungen im Fenster nach Kapitel 5.1 gelten nicht als Ausfall, sofern sie mindestens sieben Tage vorher angekündigt wurden.

Tabelle 4: Verfügbarkeits- und Wiederanlaufkennwerte

| Kennwert                       | Vorgabe      | Erläuterung                                                      |
|--------------------------------|--------------|------------------------------------------------------------------|
| Zielverfügbarkeit Produktion   | 99,9 %       | entspricht höchstens 8 h 45 min Ausfall im Jahr                  |
| Gemessene Verfügbarkeit        | 99,97 %      | April 2025 - März 2026                                           |
| Maximale Einzelausfalldauer    | 24 h         | Vorgabe aus der Schutzbedarfsfeststellung                        |
| Maximale Ausfallhäufigkeit     | 1 × je Monat | bezogen auf Vollausfälle                                         |
| RTO (Recovery Time Objective)  | 4 h          | Wiederherstellung der Zustellfähigkeit, siehe Kapitel 8.3        |
| RPO (Recovery Point Objective) | 15 min       | ergibt sich aus der Kafka-Replikation, nicht aus einer Sicherung |
| Zielverfügbarkeit Dev und Test | 99,0 %       | ohne Rufbereitschaft, Störungsbearbeitung in der Servicezeit     |

#### Hinweis

Die Verfügbarkeit des Event-System hängt unmittelbar an der Erreichbarkeit des Hausnetzes Süd. Ein Ausfall der Kafka-Instanzen führt zum Stillstand der Zustellung, auch wenn alle Komponenten in West laufen. Dieses Szenario ist in Kapitel 8.3 beschrieben.

### 3.2 Dimensionierung

Die verbindliche Konfiguration liegt versioniert in git.bavd.intern/es-ocp-infra unter manifests/serverless/environments ; je Stage existiert eine eigene Wertedatei. Tabelle 5 gibt die daraus abgeleitete Dimensionierung der Produktionsumgebung wieder.

Tabelle 5: Dimensionierung der Event-System-Komponenten in ocp-prod

| Komponente              |   Replikas | CPU (Request/Limit)   | Speicher (Request/Limit)   | Bemerkung                                                                                                                                                              |
|-------------------------|------------|-----------------------|----------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| kafka-broker-receiver   |          3 | 500 m / 1             | 512 Mi / 1 Gi              | Deployment, hinter Service Mesh                                                                                                                                        |
| kafka-broker-dispatcher |          3 | 1 / 2                 | 1 Gi / 2 Gi                | StatefulSet, je Replika ein Consumer; PodDisruptionBudget minAvailable=2 - deshalb blockiert das parallele Entleeren zweier Knoten (siehe BHB-PLT-0001 , SOP-CAAS-01 ) |
| mt-broker-filter        |          3 | 200 m / 500 m         | 256 Mi / 512 Mi            | skaliert mit der Anzahl der Trigger                                                                                                                                    |

<!-- page break -->

| Komponente                 | Replikas   | CPU (Request/Limit)   | Speicher (Request/Limit)   | Bemerkung                               |
|----------------------------|------------|-----------------------|----------------------------|-----------------------------------------|
| mt-broker-ingress          | 2          | 200 m / 500 m         | 256 Mi / 512 Mi            | nur für In-Memory-Broker                |
| eventing-controller        | 1          | 100 m / 500 m         | 256 Mi / 1 Gi              | Control Plane, Leader Election          |
| kafka-controller           | 1          | 100 m / 500 m         | 256 Mi / 1 Gi              | erzeugt Topics und Konfiguration        |
| Summe Namespace-Kontingent | -          | 12 vCPU               | 24 GiB                     | Quota, Auslastung im Juni 2026 bei 46 % |

Die Dimensionierung der Kafka-Instanzen liegt bei der Talwerk IT-Services GmbH und ist in Tabelle 6 wiedergegeben. Grundlage ist eine Wachstumsannahme von 25 % Ereignisvolumen je Jahr; die Kapazitätsplanung wird halbjährlich mit dem Dienstleister überprüft (Kapitel 5.6).

Tabelle 6: Dimensionierung der Kafka-Instanzen (Produktion)

| Merkmal                            | Wert                                     |
|------------------------------------|------------------------------------------|
| Broker                             | 3 (kafka-p01 bis kafka-p03), KRaft-Modus |
| CPU / Speicher je Broker           | 8 vCPU / 32 GiB                          |
| Datenträger je Broker              | 2 TB lokale Disk, Auslastung 38 %        |
| Replikationsfaktor                 | 3                                        |
| Mindestanzahl synchroner Replikate | 2 ( min.insync.replicas )                |
| Aufbewahrung                       | 7 Tage bzw. 50 GiB je Topic              |
| Partitionen je Broker-Topic        | 3 (Standard), bis 12 auf Antrag          |
| Netzanbindung                      | 2 × 10 GBit/s, Auslastung p95 unter 5 %  |

### 3.3 Schutzbedarf

Die Schutzbedarfsfeststellung SBF-PLT-2025 ordnet dem Event-System die in Tabelle 7 genannten Schutzziele zu. Maßgeblich ist die Festlegung, dass Ereignisse keine Fachdaten enthalten (Kapitel 2.2).

Tabelle 7: Schutzbedarf und Begründung

| Schutzziel      | Schutzbedarf   | Begründung                                                                                                                                                                                                                                                                                                                |
|-----------------|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Vertraulichkeit | hoch           | Auch ohne Fachdaten lassen die Metadaten Rückschlüsse auf Vorgänge und Bearbeitungsstände zu. Ein unbefugter Zugriff oder eine Veröffentlichung hätte einen erheblichen Ansehensverlust zur Folge. Der Zugriff auf Broker und Topics ist deshalb je Bedarfsträger getrennt und wird über SASL/SCRAM und mTLS abgesichert. |
| Integrität      | mittel         | Fachdaten dürfen nicht in Ereignisse eingebettet werden, sondern werden über Referenzen verknüpft und beim fachlich zuständigen System aufgelöst. Zu gewährleisten ist lediglich, dass ein Ereignis die notwendigen Metadaten und Referenzen unverändert trägt, damit Konsumenten filtern und weiterverarbeiten können.   |
| Verfügbarkeit   | hoch           | Das Event-System wird behördenweit von Projekten und Verfahren genutzt. Ein Ausfall unterbricht die Benachrichtigung zwischen Verfahren und führt zu Rückstau in den Produzenten. Ein Ausfall darf nicht länger als 24 Stunden und nicht häufiger als einmal im Monat auftreten.                                          |

<!-- page break -->

Werden in einem Ereignis versehentlich Fachdaten übertragen, ist dies eine meldepflichtige Abweichung: Vorgang in ESSUP mit Schweregrad 2 anlegen, betroffenes Topic gemeinsam mit der Talwerk IT-Services GmbH bereinigen (SOP-7) und den Bedarfsträger sowie den Datenschutzbeauftragten über den Produktverantwortlichen informieren.

### 3.4 Anbindung an andere Schnittstellen und Basisdienste

Tabelle 8 nennt die Dienste, auf die das Event-System angewiesen ist. Fällt ein Dienst der Kategorie 'betriebskritisch' aus, ist die Zustellung beeinträchtigt oder unterbrochen.

Tabelle 8: Genutzte Basisdienste

| Dienst                                   | Nutzung durch das Event-System                                                         | Kategorie        |
|------------------------------------------|----------------------------------------------------------------------------------------|------------------|
| CaaS (OpenShift Container Platform 4.16) | Bereitstellung und Hosting aller Komponenten, Administration per oc / kubectl und YAML | betriebskritisch |
| Apache Kafka 3.9.0                       | Persistenz der Ereignisse, Anbindung über Kafka-Clients und Kafka-Protokoll (TCP 9093) | betriebskritisch |
| Red Hat OpenShift Service Mesh           | mTLS zwischen den Namespaces, Routing für Broker und Trigger                           | betriebskritisch |
| Vault ( vault.caas.bavd.intern )         | Verwaltung der Kafka-Zugangsdaten und Keystore-Kennwörter                              | betriebskritisch |
| Interne PKI (Issuing CA 3)               | Serverzertifikate der Routen und der Kafka-Broker, ACME für cert-manager               | betriebskritisch |
| IAM (Keycloak 24.0)                      | Anmeldung an Grafana und an der OpenShift-Konsole (OIDC)                               | unterstützend    |
| ArgoCD 2.12 und Git                      | Ausrollen von Konfiguration und Releases                                               | unterstützend    |
| Nexus ( nexus.bavd.intern )              | Container-Images der Komponenten                                                       | unterstützend    |
| Prometheus, Loki, Tempo, Grafana         | Überwachung, Protokollierung, Tracing                                                  | unterstützend    |
| Jira, Confluence, Mattermost             | Vorgangsbearbeitung, Dokumentation, Direktkontakt                                      | unterstützend    |

### 3.5 Weitere Anforderungen

#### Umgebungen und Stages

Das Event-System wird in vier Umgebungen parallel bereitgestellt und betreut. Änderungen durchlaufen die Stages immer aufwärts von ocp-di bis ocp-prod . So bleibt die Feature-Parität gewahrt und Randfälle werden früh erkannt (Kapitel 5.4).

Tabelle 9: Umgebungen und ihre Verwendung

| Stage      | Cluster   | Verwendung                                                                                                            | Nutzerkreis               |
|------------|-----------|-----------------------------------------------------------------------------------------------------------------------|---------------------------|
| Dev-Intern | ocp-di    | Vorabprüfung neuer Releases und Konfigurationsänderungen durch das Team Plattformdienste; In-Memory-Broker zugelassen | nur Team Plattformdienste |
| Dev        | ocp-dev   | Entwicklungsumgebung der Bedarfsträger, Kafka-Broker, Debug-Stack aktiv                                               | Bedarfsträger             |
| Test       | ocp-test  | Test- und Abnahmeumgebung, Lasttests, Abnahme durch die Bedarfsträger                                                 | Bedarfsträger             |
| Prod       | ocp-prod  | Produktion, ausschließlich Kafka-Broker, Debug-Stack deaktiviert                                                      | Bedarfsträger             |

<!-- page break -->

Für Applikationsteams hat die Dev-Umgebung praktisch die Bedeutung einer Produktionsumgebung. Das Team Plattformdienste unterscheidet deshalb bei der Störungsannahme nicht zwischen Produktion und Entwicklung; lediglich die Rufbereitschaft außerhalb der Servicezeit gilt allein für die Produktion.

#### Update- und Releasezyklus

Das Event-System nutzt Red Hat OpenShift Serverless, das gemeinsam mit der OpenShift Container Platform bereitgestellt wird; für den Einsatz ist mindestens eine OpenShift-Container-Platform-Subskription erforderlich (Kapitel 11.1). Der Update- und Releasezyklus folgt dem Zyklus von OpenShift Serverless und liegt bei etwa drei Monaten. Sicherheitsrelevante Korrekturversionen werden außerhalb dieses Zyklus eingespielt, bei kritischer Einstufung auch außerhalb des regulären Wartungsfensters mit Vorabinformation an die Bedarfsträger.

Die jeweils unterstützten Versionen und Supportfristen sind der Produktdokumentation des Herstellers zu entnehmen; der Produktverantwortliche prüft sie quartalsweise (Kapitel 5.6).

#### Ticketsystem

Bedarfsträger legen Vorgänge im Jira-Projekt ESSUP ( https://jira.bavd.intern/projects/ESSUP ) an. Tabelle 10 nennt die zulässigen Vorgangstypen und die zugesagten Reaktionszeiten. Die Reaktionszeit ist die Zeit bis zur Annahme und zum Beginn der Bearbeitung, nicht bis zur Lösung.

Tabelle 10: Vorgangstypen und Reaktionszeiten

| Vorgangstyp            | Verwendung                                                         | Reaktionszeit in der Servicezeit   |
|------------------------|--------------------------------------------------------------------|------------------------------------|
| Störung, Schweregrad 1 | Produktion vollständig ohne Zustellung                             | 30 min                             |
| Störung, Schweregrad 2 | Produktion eingeschränkt, einzelne Broker oder Trigger betroffen   | 2 h                                |
| Störung, Schweregrad 3 | Dev oder Test betroffen, Umgehung vorhanden                        | 4 h                                |
| Anfrage                | Fragen zur Nutzung, Konfigurationsauskunft, Beratung               | 1 Arbeitstag                       |
| Änderungsantrag        | neuer Broker, neuer Trigger, geänderte Partitionierung, Onboarding | 3 Arbeitstage                      |

Die zugesagten Zeiten liegen unterhalb der Servicezeiten des ZRB, von denen das Event-System mittelbar abhängt (Serviceklasse Bronze, Leistungsschein LS-ZRB-2022-5210 ). Maßgabe des Teams ist 'Best Effort': In der Praxis wird die Annahme deutlich schneller erreicht als zugesagt.

#### Direktkontakt

Der unmittelbare Kontakt zum Betriebsteam läuft über den öffentlichen Mattermost-Kanal https://chat.bavd.intern/bavd/channels/event-system . Der Kanal ersetzt keinen Vorgang: Alles, was nachvollziehbar bleiben muss, wird zusätzlich in ESSUP dokumentiert. Das Funktionspostfach eventsystem@bavd.bund.de wird in der Servicezeit gelesen; der zentrale Servicedesk ist unter 0800 1180 100 erreichbar.

<!-- page break -->

## 4 Systemüberblick

### 4.1 Fachlicher Überblick

Das Event-System setzt das Muster 'Publish/Subscribe' um. Ein Produzent sendet ein Ereignis per HTTP an den Broker-Ingress seines Brokers. Das Ereignis wird in einem Kafka-Topic persistiert und dadurch von der Verfügbarkeit der Konsumenten entkoppelt. Für jeden Konsumenten existiert ein Trigger, der über Attributfilter festlegt, welche Ereignisse ihn erreichen; der Dispatcher liest die Ereignisse aus dem Topic und stellt sie per HTTP an die im Trigger hinterlegte Zieladresse ('Sink') zu.

Ereignisse werden im Format CloudEvents 1.0 übertragen (Binärmodus, Attribute in HTTP-Kopfzeilen). Verbindlich belegt werden:

Tabelle 11: Verbindliche Attribute eines Ereignisses

| Attribut       | Bedeutung                                                        | Beispiel                  |
|----------------|------------------------------------------------------------------|---------------------------|
| ce-specversion | Version der CloudEvents-Spezifikation                            | 1.0                       |
| ce-type        | fachlicher Ereignistyp, Namensraum des Bedarfsträgers            | dd.dokument.archiviert.v1 |
| ce-source      | erzeugendes System                                               | /dd/dd-write-service      |
| ce-id          | eindeutige Kennung des Ereignisses                               | b7f1c4e2-…                |
| ce-time        | Erzeugungszeitpunkt (UTC)                                        | 2026-07-14T06:12:44Z      |
| ce-subject     | Referenz auf das fachliche Objekt, dient als Partitionsschlüssel | dok-2026-4711             |
| traceparent    | W3C-Trace-Context für die Korrelation im Tracing                 | 00-4bf92f…-01             |

Der Rumpf des Ereignisses ist auf 64 KiB begrenzt und enthält ausschließlich Metadaten und Referenzen. Größere Nutzlasten werden abgewiesen (HTTP 413).

### 4.2 Kontextdiagramm

Abbildung 1 zeigt den technischen Systemkontext der Produktionsumgebung: die Produzenten im linken Bereich, die Komponenten des Event-System auf dem Cluster ocp-prod in der Metro-Region West, die Kafka-Instanzen und zentralen Dienste im Hausnetz Süd sowie die Konsumenten auf der rechten Seite. Der Eventfluss verläuft von den Produzenten über den Broker-Ingress nach Kafka, von dort über den Dispatcher zum Trigger-Filter und schließlich zu den Konsumenten. Steuer- und Konfigurationsflüsse sind gestrichelt dargestellt.

<!-- page break -->

<!-- image -->

[Description] Das Diagramm „Event-System 2.0 – Technischer Systemkontext“ visualisiert das Zusammenspiel verschiedener Zonen: Event-Produzenten, Event-Konsumenten, die CaaS-Plattform („ZONE-APP-WE“) mit Komponenten wie Broker-Ingress, Broker-Dispatcher, Trigger-Filter, Dead-Letter-Sink und Control Plane sowie ein dreiknotiges Kafka-Cluster im „Hausnetz Süd (ZONE-APP-SD)“, Zentrale Dienste Süd und Querschnittsdienste (ZONE-MGMT). Durchgezogene Pfeile repräsentieren den eigentlichen Eventfluss von den Produzenten über CloudEvents/HTTPS 443 und Kafka (SASL_SSL 9093) bis hin zur HTTPS-Zustellung an Konsumenten oder die Dead-Letter-Sink. Gestrichelte Pfeile markieren Steuer- und Konfigurationsflüsse, darunter CRD-Reconciliation, Webhook-Validierungen sowie OIDC- und ACME-Zertifikatsanbindungen.

Abbildung 1: Technischer Systemkontext des Event-System 2.0 in der Produktionsumgebung. Der Übergang zwischen der Metro-Region West und dem Hausnetz Süd erfolgt über die Firewall-Freischaltung FW-ES-014 (TCP 9093).

Tabelle 12 beschreibt die im Kontextdiagramm genannten Nachbarsysteme.

Tabelle 12: Angebundene Systeme

| System                       | Rolle                   | Broker / Trigger                                 | Beschreibung                                                                                                                                                                                                  |
|------------------------------|-------------------------|--------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| DTP - Datentransferplattform | Produzent               | dtp-prod-broker                                  | Abstraktionsschicht für den Zugriff auf Daten verschiedener Quellen. Meldet über das Event-System, wenn ein Datenbestand aufbereitet und abrufbar ist, und entkoppelt damit Konsumenten von den Datenquellen. |
| Mars Dokumentendienste       | Produzent und Konsument | dd-prod-broker; dd-archiv-events, dd-task-events | Veröffentlicht Ereignisse zu Eingang, Archivierung und Virenfunden und bezieht Aufgabenereignisse des Task-Managers. Eigenes Betriebshandbuch BHB-VRF-0118 .                                                  |
| AntragOnline                 | Produzent               | aon-prod-broker                                  | Fachanwendung, die Zustandsänderungen an Vorgängen veröffentlicht.                                                                                                                                            |
| Task-Manager                 | Konsument               | task-events                                      | Zentraler technischer Dienst zur Verwaltung von Aufgaben, unabhängig davon, ob diese manuell, teilautomatisiert oder automatisiert erledigt werden. Erzeugt aus Ereignissen Aufgaben und Fristen.             |
| Benachrichtigungsdienst      | Konsument               | notify-events                                    | Versendet Benachrichtigungen an Postfächer und Arbeitskörbe.                                                                                                                                                  |
| Weitere Fachanwendungen      | Produzent oder          | projektspezifisch                                | Zwölf weitere Verfahren mit eigenem Broker; die vollständige Aufstellung führt die Bedarfsträgerliste                                                                                                         |

<!-- page break -->

| System   | Rolle     | Broker / Trigger   | Beschreibung    |
|----------|-----------|--------------------|-----------------|
|          | Konsument |                    | (Kapitel 12.2). |

### 4.3 Schnittstellen

Tabelle 13 listet die Schnittstellen des Event-System. Fachliche Schnittstellen sind die beiden HTTPSchnittstellen; alle übrigen dienen dem Betrieb.

Tabelle 13: Schnittstellen des Event-System

| Schnittstelle                | Richtung             | Protokoll / Port      | Partner                | Absicherung                                                       |
|------------------------------|----------------------|-----------------------|------------------------|-------------------------------------------------------------------|
| Broker-Ingress (Eingang)     | eingehend            | HTTPS 443 → HTTP 8080 | Produzenten            | Route mit Serverzertifikat, mTLS im Mesh, Netzzonenprüfung        |
| Trigger-Zustellung (Ausgang) | ausgehend            | HTTPS 443             | Konsumenten            | Serverzertifikat des Konsumenten, optional Bearer-Token aus Vault |
| Kafka-Producer / - Consumer  | bidirektional        | TCP 9093              | Kafka-Broker (Talwerk) | SASL_SSL mit SCRAM-SHA-512, Zugangsdaten aus Vault                |
| Kubernetes-API               | eingehend            | TCP 6443              | Administration, ArgoCD | OIDC-Anmeldung, RBAC, Zugriff nur über jump01.mgmt.bavd.intern    |
| Metriken                     | ausgehend (Abholung) | HTTP 9090 / 9404      | Prometheus             | ServiceMonitor, netzwerkseitig auf den Cluster begrenzt           |
| Tracing                      | ausgehend            | OTLP 4317 / 4318      | OTel-Collector, Tempo  | mTLS im Mesh, Abtastrate 10 %                                     |
| Protokollierung              | ausgehend            | intern                | Log-Forwarder, Loki    | ClusterLogForwarder , Filter je Namespace                         |
| Traffic-Management           | intern               | HTTP / mTLS           | Service Mesh           | Autorisierungsregeln je Namespace                                 |
| Geheimnisverwaltung          | ausgehend            | HTTPS 443             | Vault                  | Kubernetes-Auth, kurzlebige Token                                 |

#### Hinweis für Bedarfsträger

Die Zieladresse eines Triggers muss innerhalb von 30 Sekunden antworten und Wiederholungen verkraften. Die Zustellung erfolgt mindestens einmal ('at least once'), Duplikate sind möglich. Konsumenten müssen deshalb idempotent verarbeiten, üblicherweise über die Auswertung von ce-id .

### 4.4 Serverinstanzen

Das Event-System belegt keine eigenen Server, sondern nutzt die vier Cluster der CaaS-Plattform. Tabelle 14 nennt die Endpunkte, Tabelle 15 die zugeordneten Kafka-Instanzen. Die Zuordnung der Umgebungen zu den Clustern ist in Abbildung 2 im Detail dargestellt.

Tabelle 14: Cluster und Endpunkte

| Stage      | Cluster   | API-Endpunkt                           | Anwendungsdomäne           |   Worker |
|------------|-----------|----------------------------------------|----------------------------|----------|
| Dev-Intern | ocp-di    | https://api.di.caas.bavd.intern:6443   | apps.di.caas.bavd.intern   |        3 |
| Dev        | ocp-dev   | https://api.dev.caas.bavd.intern:6443  | apps.dev.caas.bavd.intern  |        6 |
| Test       | ocp-test  | https://api.test.caas.bavd.intern:6443 | apps.test.caas.bavd.intern |        6 |
| Prod       | ocp-prod  | https://api.prod.caas.bavd.intern:6443 | apps.prod.caas.bavd.intern |       12 |

<!-- page break -->

Die Knoten des Clusters ocp-prod sind innerhalb der Metro-Region West auf die beiden Brandabschnitte WE-A ( 10.30.1.0/24 ) und WE-B ( 10.30.2.0/24 ) verteilt und werden im Aktiv-Aktiv-Modell betrieben. Die API ist über die virtuelle Adresse 10.30.8.6 , der Anwendungsverkehr über 10.30.8.7 erreichbar.

Tabelle 15: Kafka-Instanzen je Stage

| Stage              | Broker                           | IP-Adressen    |   Port | Betrieb                  |
|--------------------|----------------------------------|----------------|--------|--------------------------|
| Dev-Intern und Dev | kafka-d01/d02/d03.mw.bavd.intern | 10.20.10.11-13 |   9093 | Talwerk IT-Services GmbH |
| Test               | kafka-t01/t02/t03.mw.bavd.intern | 10.20.11.11-13 |   9093 | Talwerk IT-Services GmbH |
| Prod               | kafka-p01/p02/p03.mw.bavd.intern | 10.20.12.11-13 |   9093 | Talwerk IT-Services GmbH |

### 4.5 Storage

Für die Kafka-Instanzen werden lokale Datenträger an die virtuellen Maschinen durchgereicht; ein StorageController ist nicht zwischengeschaltet. Die Verfügbarkeit der Ereignisse wird nicht über eine Sicherung, sondern über die Replikation aller Daten über die drei Broker eines Clusters gewährleistet. Der Replikationsfaktor beträgt 3; die Kafka-Schnittstelle quittiert das Speichern erst, wenn mindestens zwei Replikate synchronisiert sind ( acks=all , min.insync.replicas=2 ).

Innerhalb des Clusters belegt das Event-System Speicher für die Zustandshaltung des Dispatchers. Tabelle 16 fasst die Speicherobjekte zusammen.

Tabelle 16: Speicherobjekte

| Objekt                          | Ort                    | Größe                | Inhalt und Aufbewahrung                              |
|---------------------------------|------------------------|----------------------|------------------------------------------------------|
| Kafka Log- und Data-Volume      | lokale Disk je Broker  | 2 TB                 | Ereignisse, Aufbewahrung 7 Tage bzw. 50 GiB je Topic |
| Dead-Letter-Topics              | Kafka                  | im Rahmen des Topics | nicht zustellbare Ereignisse, Aufbewahrung 14 Tage   |
| PVC es-dispatcher-state         | ODF, 3-fach repliziert | 3 × 20 GiB           | Offsets und Zustand des StatefulSets                 |
| Objektspeicher es-observability | ODF (S3)               | 1,5 TB               | Loki-Chunks und Langzeitmetriken, 30 bzw. 90 Tage    |

#### Achtung

Eine Sicherung der Ereignisdaten findet bewusst nicht statt. Wer Ereignisse länger als sieben Tage benötigt, muss sie im eigenen Verfahren persistieren. Ein Wiederherstellen 'verlorener' Ereignisse aus einer Sicherung ist nicht möglich; das Wiederholen wird auf der Produzentenseite gelöst (Kapitel 8.2).

### 4.6 Anwendungen und Dienste

Abbildung 2 ordnet die Komponenten den Namespaces und den Ebenen Control Plane und Data Plane zu und gibt an, in welchen Clustern eine Komponente aktiv ist. Tabelle 17 beschreibt die Komponenten im Einzelnen.

<!-- page break -->

<!-- image -->

[Description] Das Diagramm stellt die internen Komponenten des „Event-System 2.0“ dar, gegliedert in die Namespaces `knative-eventing` (Subsystem Knative Eventing), `eventing-kafka-broker` (Subsystem Knative Kafka) sowie `event-system-ops / event-system-debug`. Die Komponenten sind farblich den Zonen *Control Plane* (u. a. `eventing-controller`, `kafka-controller`), *Data Plane* für Eventing und Kafka (z. B. `mt-broker-ingress`, `kafka-broker-receiver`, `kafka-broker-dispatcher`) sowie *Observability* (`Grafana + Prometheus`, `ce-metrics-collector`, `chronsource`) zugeordnet. Die Beschriftungen in den Komponentenboxen erläutern die jeweiligen Aufgaben, funktionale Datenflüsse (wie `HTTP → Kafka` und `Kafka → HTTP`) sowie die Umgebungen, in denen sie aktiv sind; der untere Bereich definiert ergänzend die Zuordnung zu den Stages `ocp-di`, `ocp-dev`, `ocp-test` und `ocp-prod`.

Abbildung 2: Interne Komponenten des Event-System, gegliedert nach Namespace, Control Plane und Data Plane, mit Angabe der Cluster, in denen die Komponente aktiv ist.

Tabelle 17: Komponenten des Event-System

| Anwendung                 | Cluster         | Typ           | Subsystem        | Namespace        | Beschreibung                                                                                                                                           |
|---------------------------|-----------------|---------------|------------------|------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| eventing-controller       | test, prod      | Control Plane | Knative Eventing | knative-eventing | Steuert die gesamte Eventing-Konfiguration und übernimmt die Reconciliation von Ressourcen wie Trigger, Broker, Channel und Source.                    |
| eventing-istio-controller | alle            | Control Plane | Knative Eventing | knative-eventing | Integriert Eventing mit dem Service Mesh, insbesondere die Routing-Konfiguration für Broker und Trigger.                                               |
| eventing-webhook          | dev, test, prod | Data Plane    | Knative Eventing | knative-eventing | Validiert und ergänzt Eventing-Ressourcen (Admission-Webhook) und stellt sicher, dass CRDs korrekt erzeugt und aktualisiert werden.                    |
| mt-broker-controller      | dev, test       | Control Plane | Knative Eventing | knative-eventing | Stellt für jede Broker-Ressource die notwendigen Multi-Tenant-Komponenten (Ingress und Filter) bereit.                                                 |
| mt-broker-ingress         | alle            | Data Plane    | Knative Eventing | knative-eventing | Nimmt eingehende Ereignisse für einen Multi-Tenant-Broker an und legt sie im Event-Backend ab.                                                         |
| mt-broker-filter          | alle            | Data Plane    | Knative Eventing | knative-eventing | Empfängt Ereignisse, filtert sie anhand der Trigger-Bedingungen und sendet sie an die Zieladresse.                                                     |
| imc-controller            | di, dev         | Control Plane | Knative Eventing | knative-eventing | Erzeugt und aktualisiert In-Memory-Channel-Objekte und legt die zugehörigen Deployments und Services an. Nur in den Entwicklungsumgebungen zugelassen. |
| imc-dispatcher            | di, dev         | Data Plane    | Knative Eventing | knative-eventing | Verteilt Ereignisse innerhalb eines In-Memory-Channels an die zugehörigen Subscriptions.                                                               |
| pingsource-mt-adapter     | alle            | Data Plane    | Knative Eventing | knative-eventing | Multi-Tenant-Adapter für PingSources; erzeugt zeitgesteuerte Ereignisse und sendet sie an die                                                          |

<!-- page break -->

| Anwendung                | Cluster    | Typ           | Subsystem        | Namespace             | Beschreibung                                                                                                                                                        |
|--------------------------|------------|---------------|------------------|-----------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|                          |            |               |                  |                       | konfigurierte Zieladresse. Grundlage der Heartbeat-Überwachung.                                                                                                     |
| job-sink                 | di, dev    | Data Plane    | Knative Eventing | knative-eventing      | Nimmt Ereignisse an und startet daraus Kubernetes-Jobs. Wird nur für Auswertungsläufe in den Entwicklungsumgebungen genutzt.                                        |
| kafka-controller         | alle       | Control Plane | Knative Kafka    | eventing-kafka-broker | Reconciliation-Controller für Kafka-Broker und Kafka-Channel-Ressourcen; erstellt und verwaltet Deployments, Services und Kafka-Topics.                             |
| kafka-webhook-eventing   | test, prod | Data Plane    | Knative Kafka    | eventing-kafka-broker | Validiert und ergänzt alle Kafka-spezifischen CRDs, etwa Broker- und Channel-Konfigurationen.                                                                       |
| kafka-broker-receiver    | alle       | Data Plane    | Knative Kafka    | eventing-kafka-broker | Kafka-Producer: nimmt Ereignisse per HTTP an und übermittelt sie per Kafka-Protokoll in die konfigurierten Topics. Umgesetzt mit der Client-Bibliothek sarama (Go). |
| kafka-broker-dispatcher  | alle       | Data Plane    | Knative Kafka    | eventing-kafka-broker | Kafka-Consumer: liest Ereignisse aus den Broker-Topics und verteilt sie (Fan-out) an die Trigger und deren Zieladressen. Als StatefulSet ausgeführt.                |
| kafka-channel-receiver   | di, dev    | Data Plane    | Knative Kafka    | eventing-kafka-broker | Nimmt Ereignisse für Kafka-Channels per HTTP an und schreibt sie nach Kafka.                                                                                        |
| kafka-channel-dispatcher | di, dev    | Data Plane    | Knative Kafka    | eventing-kafka-broker | Nimmt ausgehende Ereignisse per Kafka-Protokoll an und übermittelt sie per HTTP an den Filter. Als StatefulSet ausgeführt.                                          |
| Grafana und Prometheus   | test, prod | Betrieb       | Observability    | event-system-ops      | Ops-Cockpit des Teams Plattformdienste, Dashboard-UID es-ops-cockpit-v2 .                                                                                           |
| chronsource              | alle       | Betrieb       | Observability    | event-system-debug    | PingSource, erzeugt im Minutentakt Heartbeat-Ereignisse zur Verfügbarkeitsmessung.                                                                                  |
| ce-metrics-collector     | alle       | Betrieb       | Observability    | event-system-debug    | Konsument der Heartbeat-Ereignisse; zählt erfolgreiche (HTTP 200) und fehlgeschlagene Zustellungen (HTTP 400, HTTP 500).                                            |

### 4.7 Systemdiagramm

Das logische Betriebsmodell des Event-System setzt sich aus zwei Sichten zusammen, die gemeinsam das Systemdiagramm bilden: der Komponentensicht in Abbildung 2 und der Vernetzungssicht in Abbildung 3. Wesentlich für das Verständnis ist, dass die Verarbeitung zweimal die Netzgrenze überschreitet: Der Receiver in der Metro-Region West schreibt in das Hausnetz Süd, der Dispatcher liest von dort wieder zurück. Jede Störung der Verbindung zwischen den beiden Standorten wirkt sich deshalb unmittelbar auf die Zustellung aus, während ein Ausfall eines einzelnen Brandabschnitts in West durch das Aktiv-Aktiv-Modell abgedeckt ist.

### 4.8 Vernetzung

Die Dienste des Event-System werden mit Ausnahme von Apache Kafka innerhalb der BAVD DevOps Plattform bereitgestellt, die im Verfahrensnetz des BAVD in der Metro-Region West erreichbar ist. Die MetroRegion ist durch Firewalls gegen Zugriffe aus anderen Netzen abgesichert. Zugriffe von außerhalb der MetroRegion laufen über den Global Server Load Balancer (GSLB), der zusammen mit weiteren Diensten - Middleware, IAM, PKI - im Hausnetz Süd liegt. Dort befinden sich auch die vom Event-System genutzten Kafka-Instanzen.

<!-- page break -->

Abbildung 3: Netz- und Zonenarchitektur mit Portfreischaltungen. Verbindungen zwischen den Brandabschnitten WE-A und WE-B sind zonenintern und unterliegen keiner Firewall-Regel; sie werden über das Service Mesh mit mTLS abgesichert.

<!-- image -->

[Description] Das Diagramm stellt die Netz- und Zonenarchitektur des „Event-System 2.0“ dar, gegliedert in die drei Zonen **ZONE-EXT** (Behördennetz/Bundesnetz mit Arbeitsplatz-Clients, Fachanwendungen, Administration und ZRB-Netzübergang), **ZONE-APP-WE** (Metro-Region West, unterteilt in die Brandabschnitte WE-A und WE-B mit OpenShift-Workern, Ingress, Control Plane, Service Mesh und ODF-Storage) sowie **ZONE-APP-SD** (Hausnetz Süd mit GSLB, Apache-Kafka-Cluster, IAM Keycloak und PKI). 

Zonenübergänge verlaufen über ein zentrales Firewall-Cluster (`FW-WE-01 / FW-WE-02`), dessen zugehörige Portfreischaltungen und Zwecke tabellarisch in der Portmatrix (Regeln FW-ES-001 bis FW-ES-021) aufgeschlüsselt sind. 

Die durchgezogenen und gestrichelten Pfeile mit Beschriftungen wie TCP 443, 6443, 9093, OIDC/LDAPS und ACME kennzeichnen die freigegebenen Daten- und Steuerverkehrsflüsse zwischen den Komponenten, während die zoneninterne Verbindung zwischen den Brandabschnitten WE-A und WE-B über das Service Mesh mittels mTLS erfolgt.

Tabelle 18 enthält die für den Betrieb wesentlichen Regeln; die vollständige Liste FW-ES-001 bis FW-ES-021 führt der Netzbetrieb. Änderungen erfolgen ausschließlich über einen Change beim Netzbetrieb (Frank Dettmer, netzbetrieb@bavd.bund.de ) mit einem Vorlauf von fünf Arbeitstagen.

Tabelle 18: Portmatrix des Event-System (Produktion)

| Regel     | Quelle      | Ziel           | Port          | Protokoll    | Zweck                                                     |
|-----------|-------------|----------------|---------------|--------------|-----------------------------------------------------------|
| FW-ES-001 | ZONE-EXT    | 10.30.8.7      | TCP 443       | HTTPS        | Zugriff der Bedarfsträger auf den Broker-Ingress          |
| FW-ES-004 | 10.30.8.7   | ZONE-EXT       | TCP 443       | HTTPS        | Zustellung an die Zieladressen der Konsumenten            |
| FW-ES-007 | ZONE-MGMT   | 10.30.8.6      | TCP 6443      | HTTPS        | oc und kubectl der Administration, nur vom Jumphost       |
| FW-ES-011 | ZONE-EXT    | 10.20.4.10     | TCP 443       | HTTPS        | Zugriff über den GSLB von außerhalb der Metro-Region West |
| FW-ES-014 | ZONE-APP-WE | 10.20.12.11-13 | TCP 9093      | SASL_SSL     | Kafka-Producer und -Consumer des Event-System             |
| FW-ES-015 | ZONE-APP-WE | 10.20.12.11-13 | TCP 9404      | HTTP         | Abholung der Kafka-Metriken durch Prometheus              |
| FW-ES-018 | ZONE-APP-WE | 10.20.6.20     | TCP 443 / 636 | OIDC / LDAPS | Anmeldung an Grafana und OpenShift-Konsole                |
| FW-ES-021 | ZONE-APP-WE | 10.20.6.40     | TCP 443       | ACME         | automatische Zertifikatserneuerung durch cert-manager     |

<!-- page break -->

### 4.9 Paket- und Versionsübersicht

Tabelle 19 gibt den Versionsstand zum 24.07.2026 wieder. Die Übersicht wird bei jedem Release fortgeschrieben; der maschinell erzeugte Stand liegt in Confluence unter display/PLT/Versionsstand .

Tabelle 19: Paket- und Versionsübersicht (Stand 24.07.2026)

| Umgebung   | Typ            | Software                             | Version   | Anmerkung                                |
|------------|----------------|--------------------------------------|-----------|------------------------------------------|
| alle       | Plattform      | Red Hat OpenShift Container Platform | 4.16.21   | Betrieb durch das CaaS-Team              |
| alle       | Hosting        | Red Hat OpenShift Serverless         | 1.36      | enthält Knative Eventing                 |
| alle       | Hosting        | Knative Eventing                     | 1.15      | Broker, Trigger, Channel, Source         |
| alle       | Persistenz     | Apache Kafka                         | 3.9.0     | KRaft-Modus, Betrieb Talwerk IT-Services |
| alle       | Zusatzdienst   | Quarkus                              | 3.24      | Laufzeit des ce-metrics-collector        |
| alle       | Zusatzdienst   | cert-manager                         | 1.14.5    | ACME gegen die interne PKI               |
| alle       | Bereitstellung | ArgoCD                               | 2.12.3    | GitOps, Self-Heal aktiv                  |
| test, prod | Observability  | Grafana                              | 11.3      | Ops-Cockpit                              |
| alle       | Observability  | Prometheus                           | 2.54      | Abtastintervall 30 s                     |
| alle       | Observability  | Grafana Tempo                        | 2.6       | Traces, Aufbewahrung 7 Tage              |
| alle       | Observability  | Grafana Loki                         | 3.2       | Protokolle, Aufbewahrung 30 Tage         |

### 4.10 Ablauf der Eventzustellung

Abbildung 4 zeigt den vollständigen Ablauf am Beispiel eines Ereignisses der Mars Dokumentendienste, das an den Task-Manager zugestellt wird - einschließlich der Wiederholung bei einem nicht erreichbaren Konsumenten und der Ablage im Dead-Letter-Topic.

<!-- page break -->

<!-- image -->

[Description] Das Sequenzdiagramm stellt die Nachrichtenverarbeitung im „Event-System 2.0“ zwischen den sechs Komponenten `dd-write-service` (Produzent), `Broker-Ingress`, `Kafka-Topic`, `Broker-Dispatcher`, `Trigger-Filter` und `Task-Manager` (Konsument) dar. Der Ablauf gliedert sich vertikal in vier Abschnitte: „Phase 1 – Annahme...“, „Phase 2 – Zustellung“, „Phase 3 – Wiederholung bei Fehler“ und „Phase 4 – Dead-Letter“. Die nummerierten Pfeile (Schritte 1 bis 16) beschreiben den Nachrichtenfluss, wobei durchgezogene Pfeile Aufrufe und Übertragungen (wie POST oder Kafka-Produce/Fetch), gestrichelte Linien Rückmeldungen (wie HTTP-Statuscodes und Acks) sowie gebogene Pfeile interne Schritte (Filterprüfung, Backoff-Wartezeiten und Metrik-Zählung) darstellen.

Abbildung 4: Zustellung eines Ereignisses in vier Phasen: Annahme und Persistenz, Zustellung, Wiederholung bei Fehler, Dead-Letter. Die Korrelation über alle Beteiligten erfolgt mit dem Header traceparent .

Die Annahme gilt als abgeschlossen, sobald Kafka das Speichern mit mindestens zwei synchronen Replikaten quittiert hat; erst dann antwortet der Receiver dem Produzenten mit HTTP 202. Ein Produzent, der HTTP 202 erhalten hat, darf sein Ereignis als übergeben betrachten. Tabelle 20 nennt die Zustellparameter.

Tabelle 20: Zustellparameter und Garantien

| Parameter                    | Wert                 | Erläuterung                                                                                      |
|------------------------------|----------------------|--------------------------------------------------------------------------------------------------|
| Zustellgarantie              | at least once        | Duplikate sind möglich, Konsumenten müssen idempotent verarbeiten                                |
| Reihenfolge                  | je Partition         | Partitionsschlüssel ist ce-subject ; eine globale Reihenfolge über alle Ereignisse besteht nicht |
| Zustellversuche              | 5                    | erster Versuch plus vier Wiederholungen                                                          |
| Wartezeit zwischen Versuchen | 200 ms, exponentiell | vier Wartezeiten: 200 ms, 400 ms, 800 ms, 1,6 s                                                  |
| Zeit bis zum Dead-Letter     | ca. 3,4 s            | Summe der Versuche einschließlich Antwortzeiten                                                  |
| Zeitlimit je Zustellung      | 30 s                 | danach gilt der Versuch als fehlgeschlagen                                                       |
| Dead-Letter-Ziel             | <broker>-dlq         | eigenes Topic je Broker, Aufbewahrung 14 Tage                                                    |
| Annahme (p95)                | unter 80 ms          | gemessen Receiver bis HTTP 202                                                                   |
| Zustellung (p95)             | unter 250 ms         | gemessen Dispatcher bis Antwort des Konsumenten                                                  |

<!-- page break -->

Ereignisse im Dead-Letter-Topic werden nicht automatisch erneut zugestellt. Das Wiedereinspielen erfolgt nach Klärung mit dem Bedarfsträger über das Hilfsmittel es-utilities/dlq-replay (Kapitel 5.7) und wird im zugehörigen Vorgang dokumentiert.

<!-- page break -->

## 5 Administration

### 5.1 Servicezeiten und Wartungsfenster

- Betriebszeiten: 24 Stunden an 7 Tagen.
- Servicezeiten des Betriebsteams: Montag bis Donnerstag 08:00-16:00 Uhr, Freitag 08:00-14:00 Uhr.
- Rufbereitschaft: außerhalb der Servicezeit für Störungen des Schweregrads 1 in der Produktion, Erreichbarkeit über den Servicedesk 0800 1180 100 .
- Wartungsfenster: Mittwoch ab 17:00 Uhr. Es kann für kritische Updates mit Vorabinformation und für geplante Releasewechsel mit einer Vorankündigung von sieben Tagen genutzt werden.
- Betriebskalender: Die wochenweise Besetzung des First- und Third-Level-Supports steht im Betriebskalender ( https://confluence.bavd.intern/display/PLT/Betriebskalender ).

Innerhalb der Servicezeiten ist es das Ziel, eingestellte Störungen innerhalb der in Tabelle 10 genannten Zeiten anzunehmen und mit der Entstörung zu beginnen. Hintergrund der Fristen sind auch die Servicezeiten des ZRB, von denen das Event-System mittelbar betroffen ist: Die vom BAVD genutzte Serviceklasse 'Bronze' liegt zeitlich unterhalb der hier genannten Servicezeiten.

Die Maßgabe des Teams lautet 'Best Effort'. Auch wenn formal vier Stunden bis zur Störungsannahme vergehen dürfen, wird in der Praxis während der Funktionszeiten deutlich schneller reagiert - und zwar nicht nur bei Störungen, sondern auch bei Fragen zur Nutzung im normalen Tagesgeschäft.

### 5.2 Zugänge und Nutzerverwaltung

Administrative Zugänge zur Control Plane und zur Data Plane der Cluster werden durch das Team CaaSPlattformbetrieb verwaltet. Die Zuordnung der Berechtigungen erfolgt deklarativ über die Projektkonfiguration im Repository es-ocp-infra ; ein Antrag wird als Pull-Request gestellt und von Andreas Wehrle geprüft. Administrative Zugänge zu den Kafka-Servern verwaltet die Talwerk IT-Services GmbH.

Die Anmeldung erfolgt ausschließlich über das IAM (Keycloak, Realm bavd-intern ); lokale Konten auf den Clustern sind nicht zugelassen. Tabelle 21 nennt die Rollen.

Tabelle 21: Rollen und Berechtigungen

| Rolle (AD-Gruppe)           | Rechte                                                                                                       | Zugewiesen an                        |
|-----------------------------|--------------------------------------------------------------------------------------------------------------|--------------------------------------|
| BAVD-PLT-EventSystem-Admin  | Vollzugriff auf die Namespaces des Event-System, Änderung von Brokern und Triggern, Neustart von Komponenten | Team Plattformdienste (5 Personen)   |
| BAVD-PLT-EventSystem-Read   | Lesezugriff auf Ressourcen, Protokolle und Metriken                                                          | Bedarfsträger, CaaS-Plattformbetrieb |
| BAVD-PLT-EventSystem-Deploy | technische Kennung für ArgoCD, ausschließlich deklarative Änderungen                                         | Dienstkonto svc-es-argocd            |
| BAVD-PLT-Grafana-Ops        | Bearbeiten der Dashboards im Ops-Cockpit                                                                     | Team Plattformdienste                |
| es-kafka-admin              | Kafka-Administration (Topics, ACLs), außerhalb des BAVD-IAM verwaltet                                        | Talwerk IT-Services GmbH             |

<!-- page break -->

#### Umgang mit Geheimnissen

Geheimnisse der Software und der Plattform werden ausschließlich in Vault verwaltet. Tabelle 22 nennt die verwendeten Pfade. Ablagen in Dateisystemen, Tabellenkalkulationen oder lokalen Passwortdateien sind nicht zulässig; teaminterne Zugangsdaten liegen im Team-Namespace von Vault und werden über die Gruppenmitgliedschaft freigegeben.

Tabelle 22: Geheimnisse in Vault

| Pfad                              | Inhalt                                                                         | Rotation                             |
|-----------------------------------|--------------------------------------------------------------------------------|--------------------------------------|
| kv/event-system/kafka/scram       | SASL/SCRAM-Zugangsdaten der Konten es-broker-receiver und es-broker-dispatcher | halbjährlich, mit Talwerk abgestimmt |
| kv/event-system/tls/broker        | Keystore-Kennwort und Zertifikatskette der Kafka-Verbindung                    | bei jeder Zertifikatserneuerung      |
| kv/event-system/grafana/oidc      | Client-Secret der Grafana-Anmeldung                                            | jährlich, mit dem IAM abgestimmt     |
| kv/event-system/argocd/deploy-key | Schlüssel für den Lesezugriff auf die Git-Repositories                         | jährlich                             |

### 5.3 Aufnahme und Unterbrechung des Betriebs

#### Erstmalige Aufnahme des Betriebes

Die Ersteinrichtung einer Stage ist in SOP-1 und SOP-2 beschrieben und läuft in dieser Reihenfolge:

1. Operator 'OpenShift Serverless' über die Cluster-Konfiguration in es-ocp-infra installieren (Pull-Request an das CaaS-Team).
2. Custom Resource KnativeEventing mit der stagespezifischen Wertedatei ausrollen; Abschluss abwarten ( oc -n knative-eventing get knativeeventing knative-eventing -o jsonpath='{.status.conditions}' ).
3. Kafka-Zugangsdaten aus Vault in den Namespace eventing-kafka-broker übernehmen und die Verbindung prüfen.
4. Global-Broker und Dead-Letter-Konfiguration ausrollen (SOP-2).
5. Observability-Stack ausrollen: chronsource , ce-metrics-collector , Dashboards (SOP-3).
6. Funktionalen Test ausführen (Kapitel 5.7) und das Ergebnis im Vorgang dokumentieren.

#### Geordnetes Stoppen und Starten

Ein vollständiges Stoppen ist nur für Wartungen an Kafka oder am Cluster erforderlich. Die Reihenfolge ist einzuhalten, damit keine Ereignisse verloren gehen und keine unnötigen Wiederholungen ausgelöst werden.

#### Stoppen:

1. Bedarfsträger informieren (Mattermost und Vorgang), Beginn und erwartete Dauer nennen.
2. Zustellung anhalten: Dispatcher auf null skalieren ( oc -n eventing-kafka-broker scale statefulset kafka-broker-dispatcher --replicas=0 ). Ereignisse bleiben in Kafka erhalten.
3. Annahme anhalten: Receiver auf null skalieren. Produzenten erhalten ab jetzt HTTP 503 und müssen puffern.
4. Control Plane anhalten: eventing-controller und kafka-controller auf null skalieren.
5. Wartung durchführen.

<!-- page break -->

Starten: in umgekehrter Reihenfolge - Control Plane, Receiver, Dispatcher. Nach dem Start ist der Consumer-Lag zu beobachten, bis er auf den Ausgangswert zurückgeht; Richtwert nach einer Stunde Unterbrechung sind etwa zehn Minuten Aufholzeit.

```
oc -n eventing-kafka-broker rollout status statefulset/kafka-broker-dispatcher oc -n event-system-ops exec deploy/prometheus -- \ promtool query instant http://localhost:9090 'max(kafka_consumergroup_lag)'
```

#### Achtung

Der Receiver darf nie länger gestoppt bleiben, als die Produzenten puffern können. Für die angebundenen Verfahren ist eine Pufferzeit von mindestens 60 Minuten vereinbart; längere Unterbrechungen sind vorab je Bedarfsträger abzustimmen.

### 5.4 Installation und Release-/Updatewechsel

Alle Änderungen werden ausschließlich über Git eingebracht; ein manuelles Deployment im Cluster ist nicht zulässig, weil ArgoCD den Zustand mit aktivem Self-Heal innerhalb von drei Minuten überschreiben würde. Abbildung 5 zeigt den Weg einer Änderung über die vier Stages einschließlich der Freigaben und des Rollbacks.

Abbildung 5: Release- und Konfigurationsweg über die Stages. Die Freigabe zwischen den Stages erteilt der Produktverantwortliche (Tobias Reinhardt) oder seine Vertretung (Nadine Schäfer).

<!-- image -->

[Description] Das Diagramm stellt den GitOps-basierten Release- und Konfigurationsweg für das „Event-System 2.0“ dar, ausgehend von Quell-Repositories auf `git.bavd.intern` (`es-ocp-infra`, `es-config`, `es-utilities`) über die Bereitstellungskomponente `ArgoCD 2.12` hin zu vier aufeinanderfolgenden Stages (`ocp-di`, `ocp-dev`, `ocp-test` und `ocp-prod`). Pfeile und Beschriftungen verdeutlichen dabei den linearen Ablauf vom Merge-Request über die automatische bzw. manuelle Synchronisation (Sync) bis hin zu den zwischen den Umgebungen erforderlichen Freigabeschritten. Ergänzend beschreiben separate Abschnitte eine sechsstufige Prozesstabelle („Schritte je Stage“), den Ablauf eines zulässigen Rollbacks via Git-Revert sowie eine Übersicht des Software-Versionsstands nach dem Release.

Der Ablauf je Stage folgt sechs Schritten: Fork mit dem Upstream synchronisieren, temporären Branch anlegen und Änderung vornehmen, Pull-Request an das CaaS-Team stellen, ArgoCD-Application anlegen oder aktualisieren, funktionalen Test ausführen und das Ergebnis in Confluence dokumentieren. Die SyncRichtlinie ist in ocp-di und ocp-dev automatisch, ab ocp-test manuell.

Für den Wechsel auf eine neue Version von OpenShift Serverless gilt zusätzlich:

<!-- page break -->

1. Freigabehinweise des Herstellers auf inkompatible Änderungen prüfen, insbesondere an den CRDs.
2. Unterschiede zwischen den OpenShift-Ressourcen und den Upstream-Ressourcen abgleichen (Confluence, display/PLT/Ressourcenvergleich ).
3. Auf ocp-di ausrollen, Duplikatstest und funktionalen Test ausführen.
4. Auf ocp-dev und ocp-test ausrollen, Lasttest mit Hyperfoil (Kapitel 9), Abnahme durch mindestens zwei Bedarfsträger.
5. Produktion im Wartungsfenster, Vorankündigung sieben Tage, Rufbereitschaft des 3rd Level für 24 Stunden.

Rollback: Fehler erkannt → git revert <commit> im betroffenen Repository → ArgoCD-Sync. Die Wiederherstellung des vorherigen Zustands ist nach weniger als zehn Minuten abgeschlossen. Ein Rollback der Kafka-Topics ist nicht erforderlich und nicht möglich; bereits angenommene Ereignisse bleiben unverändert erhalten.

### 5.5 Standard Operating Procedures

Tabelle 23 nennt die SOPs des Event-System. Die vollständigen Anweisungen stehen in Confluence unter display/PLT/Standard+Operating+Procedures ; dieses Handbuch verweist bewusst auf die Einzelseiten, damit Angaben nicht doppelt gepflegt werden.

Tabelle 23: Standard Operating Procedures

| SOP   | Titel                                                       | Auslöser                                                | Verantwortlich                                |
|-------|-------------------------------------------------------------|---------------------------------------------------------|-----------------------------------------------|
| SOP-1 | Bereitstellung der korrekten Knative-Eventing-Konfiguration | neue Stage, Versionswechsel                             | Team Plattformdienste                         |
| SOP-2 | Bereitstellung des Global-Brokers                           | Ersteinrichtung, Änderung der Dead-Letter-Konfiguration | Team Plattformdienste                         |
| SOP-3 | Bereitstellung des Observability-Stacks                     | Ersteinrichtung, neues Dashboard                        | Miriam Falk                                   |
| SOP-4 | Leitfaden zur Kommunikation mit Bedarfsträgern              | Störung, Wartung, Änderung                              | Sven Lorenz                                   |
| SOP-5 | Onboarding von Bedarfsträgern                               | Anfrage eines Projekts                                  | Nadine Schäfer                                |
| SOP-6 | CA- und TLS-Zertifikate erneuern                            | Alert TLSCertExpirySoon , CA-Wechsel                    | Jonas Brinkmann                               |
| SOP-7 | Kafka-Topic bereinigen                                      | fehlerhafte Ereignisse, Datenschutzvorfall              | Team Plattformdienste mit Talwerk IT-Services |

### 5.6 Regelmäßige betriebliche Tätigkeiten

Tabelle 24 listet die wiederkehrenden Tätigkeiten. Der Nachweis wird im Betriebskalender oder im jeweiligen Vorgang geführt.

Tabelle 24: Regelmäßige betriebliche Tätigkeiten

| Tätigkeit                                                    | Turnus         | Verantwortlich                 | Nachweis                    |
|--------------------------------------------------------------|----------------|--------------------------------|-----------------------------|
| Sichtprüfung Ops-Cockpit, offene Alerts, Dead-Letter-Bestand | arbeitstäglich | First Level (Betriebskalender) | Eintrag im Betriebskalender |
| Consumer-Lag und Zustelldauer gegen die Schwellwerte prüfen  | arbeitstäglich | First Level                    | Eintrag im Betriebskalender |

<!-- page break -->

| Tätigkeit                                                       | Turnus                         | Verantwortlich                     | Nachweis                            |
|-----------------------------------------------------------------|--------------------------------|------------------------------------|-------------------------------------|
| Bestand im Dead-Letter-Topic aufarbeiten oder verwerfen         | wöchentlich                    | Sven Lorenz                        | Vorgang in ESSUP                    |
| Restlaufzeit aller Zertifikate prüfen                           | wöchentlich                    | Jonas Brinkmann                    | Panel 'Zertifikatsrestlaufzeit'     |
| Funktionalen Test in allen Stages ausführen                     | wöchentlich                    | Team Plattformdienste              | Testprotokoll in Confluence         |
| Kafka-Kapazität und Topic-Wachstum mit dem Dienstleister prüfen | monatlich                      | Jonas Brinkmann mit Holger Pietsch | Protokoll der Betriebsrunde         |
| Betriebsbericht mit Kennzahlen erstellen                        | monatlich                      | Tobias Reinhardt                   | Confluence, Seite 'Betriebsbericht' |
| Supportfristen der eingesetzten Versionen prüfen                | quartalsweise                  | Tobias Reinhardt                   | Versionsübersicht (Tabelle 19)      |
| Berechtigungen und technische Konten überprüfen                 | halbjährlich                   | Nadine Schäfer mit Kai Ostermann   | Prüfprotokoll                       |
| Wiederanlauf einer Stage üben (Kapitel 8.5)                     | halbjährlich                   | Team Plattformdienste              | Übungsprotokoll                     |
| Lasttest mit aktuellem Lastprofil                               | jährlich und vor Hauptreleases | Miriam Falk                        | Testbericht                         |

### 5.7 Skripte und Automatisierung

Tabelle 25 nennt die Repositories und Hilfsmittel. Alle Skripte sind versioniert; eine Ausführung gegen die Produktion erfordert einen Vorgang und erfolgt vom Jumphost jump01.mgmt.bavd.intern aus.

Tabelle 25: Repositories und Hilfsmittel

| Repository / Hilfsmittel     | Inhalt                                                                                                                          |
|------------------------------|---------------------------------------------------------------------------------------------------------------------------------|
| es-ocp-infra                 | Cluster-Operatoren, KnativeEventing -Ressource, Wertedateien je Stage, Projektkonfiguration der Berechtigungen                  |
| es-config                    | Broker, Trigger, Dead-Letter-Konfiguration, Netzwerkregeln, Dashboards als JSON                                                 |
| es-utilities                 | Werkzeuge für den Betrieb: functional-test (Go), load-test (Hyperfoil-Profile), tls-check , dlq-replay , topic-cleanup          |
| es-utilities/functional-test | sendet je Broker ein Testereignis und prüft die Zustellung an eine Testsenke; Laufzeit etwa 90 Sekunden je Stage                |
| es-utilities/dlq-replay      | liest Ereignisse aus einem Dead-Letter-Topic und stellt sie erneut in den Broker ein; nur nach Abstimmung mit dem Bedarfsträger |
| es-utilities/topic-cleanup   | unterstützt SOP-7 beim Entfernen fehlerhafter Ereignisse aus einem Topic                                                        |

cd es-utilities/functional-test

export EG_ENV=test

go run ./cmd/eventcheck --broker global-broker --timeout 30s

<!-- page break -->

| Merkmal   | Festlegung                                                           |
|-----------|----------------------------------------------------------------------|
| Ablage    | Zertifikatskette und Keystore-Kennwort in kv/event-system/tls/broker |

#### Weg A - Routen und Service Mesh (automatisiert)

1. Betroffenes Objekt aus dem Alert ablesen und Vorgang in ESSUP anlegen (Typ 'Wartung').
2. Zustand der Zertifikate prüfen:
3. Normalfall: cert-manager erneuert 30 Tage vor Ablauf selbstständig. Bleibt die Erneuerung aus, Ursache im Protokoll des cert-managers suchen (häufig: ACME-Anfrage durch die Firewall blockiert, Regel FW-ES-021 ) und die Erneuerung erzwingen:
4. Ergebnis prüfen - Ablaufdatum, Ausstellerkette und Übereinstimmung des SAN:
5. Ein Neustart ist nicht erforderlich: Der Router liest das erneuerte Secret selbstständig neu ein. Nur wenn eine Anwendung das Zertifikat zwischenspeichert, ist oc rollout restart deployment/<name> nötig.
6. Vorgang mit dem neuen Ablaufdatum schließen und die Zertifikatsübersicht in Confluence aktualisieren.

```
oc get certificate -A | grep -v True oc -n knative-eventing describe certificate es-broker-ingress-tls
```

```
cmctl renew es-broker-ingress-tls -n knative-eventing oc -n cert-manager logs deploy/cert-manager --since=10m | grep -i acme
```

```
openssl s_client -connect broker-ingress.apps.prod.caas.bavd.intern:443 \ -servername broker-ingress.apps.prod.caas.bavd.intern /dev/null \ | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
```

#### Weg B - Kafka-Verbindung (manuell)

1. Schlüsselpaar und Zertifikatsanforderung erzeugen. Alle Namen, unter denen der Broker erreichbar ist, gehören in den SAN-Eintrag:
2. Antrag im Jira-Projekt PKI stellen, die Anforderung als Anhang beifügen, Verwendungszweck und Ablaufdatum des alten Zertifikats angeben.
3. Der PKI-Betrieb prüft Berechtigung, SAN und Laufzeit, stellt das Zertifikat aus und liefert die vollständige Kette (Root CA 2 und Issuing CA 3) zurück. Kette und Kennwort werden in kv/event-system/tls/broker abgelegt.
4. Termin im Wartungsfenster (Mittwoch ab 17:00 Uhr) mit einem Vorlauf von sieben Tagen mit der Talwerk ITServices GmbH abstimmen und die Bedarfsträger informieren.
5. Der Dienstleister tauscht Keystore und Truststore der Broker kafka-p01 bis kafka-p03 und startet die Broker versetzt neu - ein Broker je zehn Minuten, dazwischen muss die Zahl der synchronen Replikate wieder den Sollwert erreichen:

```
openssl req -new -newkey rsa:3072 -nodes \ -keyout kafka-p01.key -out kafka-p01.csr \ -subj "/CN=kafka-p01.mw.bavd.intern/O=BAVD/C=DE" \ -addext "subjectAltName=DNS:kafka-p01.mw.bavd.intern,DNS:kafka-p01,IP:10.20.12.11"
```

```
oc -n event-system-ops exec deploy/prometheus -- \ promtool query instant http://localhost:9090 'kafka_under_replicated_partitions'
```

<!-- page break -->

## 6. Funktionstest ausführen und die Verbindung prüfen:

```
cd es-utilities/tls-check ./tls-check.sh --broker kafka-p01.mw.bavd.intern:9093 --expect-issuer "BAVD Issuing CA 3" go run ./cmd/eventcheck --broker global-broker --env prod
```

## 7. Dokumentation in Confluence, Vorgang schließen.

### Achtung - häufigster Fehler

Wird eine neue ausstellende CA eingeführt, muss sie vor dem Tausch der Serverzertifikate im Truststore der Pods kafka-broker-receiver und kafka-broker-dispatcher vorhanden sein. Fehlt sie, bricht die Verbindung mit einer SSLHandshakeException ab und die Zustellung bleibt stehen (siehe Kapitel 6.3.2, Vorgang ESSUP-1517).

<!-- page break -->

## 6 Troubleshooting

### 6.1 First-Level-Support und Meldewege

Der First-Level-Support ist die erste Anlaufstelle für alle Projekte mit einem technischen Problem. Er überwacht die Funktionsfähigkeit des Event-System, löst möglichst viele Probleme beim ersten Kontakt - überwiegend fehlerhafte Konfigurationen - und leitet andernfalls an den 2nd oder 3rd Level weiter. Die wochenweise Besetzung steht im Betriebskalender.

Tabelle 27: Meldewege

| Kanal               | Adresse                                           | Verwendung                                                               |
|---------------------|---------------------------------------------------|--------------------------------------------------------------------------|
| Jira                | https://jira.bavd.intern/projects/ESSUP           | verbindlicher Weg für Störungen, Anfragen und Änderungsanträge           |
| Mattermost          | chat.bavd.intern → #event-system                  | kurze Rückfragen, Abstimmung während einer Störung                       |
| Funktionspostfach   | event-system@bavd.bund.de                         | Meldungen ohne Jira-Zugang, Lesen in der Servicezeit                     |
| Servicedesk         | 0800 1180 100                                     | Schweregrad 1 außerhalb der Servicezeit, Alarmierung der Rufbereitschaft |
| Ops-Cockpit         | grafana.caas.bavd.intern/d/es-ops-cockpit-v2      | eigene Überwachung des Betriebsteams                                     |
| Zentrales Dashboard | grafana.caas.bavd.intern/d/caas-eventing-overview | Sicht über alle Namespaces für Bedarfsträger                             |

### 6.2 Vorgehen bei Störungen

Aufgabe des Betriebsteams ist es, Störungen im Event-System und Probleme der Projekte so schnell wie möglich zu beheben. Die ausführlichen Anweisungen stehen in den Runbooks

( https://confluence.bavd.intern/display/PLT/Runbooks ), der Notfallbetrieb ist in Kapitel 8.4 beschrieben. Bei jeder Störung sind zuerst diese fünf Prüfungen durchzuführen:

1. Reicht es überhaupt bis zum Broker? Heartbeat-Metrik heartbeat_missing_total im Ops-Cockpit prüfen. Fehlt der Heartbeat, ist die Plattform oder Kafka betroffen, nicht ein einzelner Bedarfsträger.
2. Nehmen die Komponenten Ereignisse an?
3. Steht die Verbindung in das Hausnetz Süd? Metriken kafka_under_replicated_partitions und kafka_consumergroup_lag prüfen; bei Auffälligkeiten die Talwerk IT-Services GmbH einbeziehen.
4. Ist die Konfiguration gültig?
5. Ist der Konsument erreichbar? Dead-Letter-Bestand und die Antwortcodes im Ops-Cockpit prüfen; bei HTTP 503 liegt die Ursache regelmäßig beim Konsumenten.

```
oc -n eventing-kafka-broker get pods oc -n eventing-kafka-broker logs deploy/kafka-broker-receiver --tail=100 | grep -Ei "error|refused"
```

```
oc get brokers.eventing.knative.dev -A oc get triggers.eventing.knative.dev -A -o wide | grep -v True
```

<!-- page break -->

Störungen mit Schweregrad 1 werden zusätzlich im Kanal #event-system angekündigt, damit Bedarfsträger nicht parallel Vorgänge anlegen. Nach der Behebung wird der Vorgang mit Ursache und Maßnahme in die Incident-Liste (Kapitel 6.4) übernommen.

### 6.3 Dokumentierte Störungsbilder

#### 6.3.1 Consumer-Lag steigt, Zustellung verzögert sich

##### Umgebung

Produktion, ocp-prod , Broker eines Bedarfsträgers; erstmals dokumentiert in ESSUP-1482.

##### Fehlerbeschreibung

Der Alert KafkaConsumerLag meldet mehr als 5 000 unverarbeitete Nachrichten. Ereignisse werden weiterhin angenommen, erreichen die Konsumenten aber mit mehreren Minuten Verzögerung. Im Protokoll des Dispatchers:

```
{"level":"warn","ts":"2026-06-03T09:14:22.512Z","logger":"kafka-broker-dispatcher", "msg":"retrying event delivery","trigger":"task-events","attempt":3, "response_code":503,"target":"http://task-manager.tm-prod.svc.cluster.local:8080"}
```

##### Lösung

Antwortverhalten des Konsumenten prüfen. Im dokumentierten Fall war der Task-Manager wegen eines eigenen Datenbankproblems überlastet. Nach dessen Behebung baute der Dispatcher den Rückstand in 18 Minuten selbstständig ab. Ein Eingriff am Event-System war nicht erforderlich und wäre schädlich gewesen, weil ein Neustart des StatefulSets die Aufholphase verlängert.

##### Hauptursache

Der Konsument antwortete mit HTTP 503 und erzwang damit fünf Zustellversuche je Ereignis. Die Zustellrate sank auf ein Fünftel.

##### Schritte zur Nachbildung

In ocp-test eine Testsenke bereitstellen, die HTTP 503 zurückgibt, den Trigger darauf richten und 10 000 Ereignisse mit es-utilities/load-test einspielen.

#### 6.3.2 SSLHandshakeException nach Wechsel der ausstellenden CA

##### Umgebung

Produktion, nach dem Tausch der Kafka-Serverzertifikate im Wartungsfenster; Vorgang ESSUP-1517.

##### Fehlerbeschreibung

Unmittelbar nach dem Neustart des ersten Brokers bricht die Zustellung vollständig ab. Receiver und Dispatcher melden im Sekundentakt:

```
ERROR [kafka-broker-dispatcher] failed to connect to kafka-p01.mw.bavd.intern:9093 javax.net.ssl.SSLHandshakeException: PKIX path building failed: unable to find valid certification path to requested target
```

##### Lösung

Neue Issuing-CA in den Truststore der Pods aufnehmen und die Data Plane neu starten:

```
oc -n eventing-kafka-broker create configmap kafka-ca-bundle \ --from-file=ca-bundle.crt=bavd-chain.pem --dry-run=client -o yaml | oc apply -f - oc -n eventing-kafka-broker rollout restart statefulset/kafka-broker-dispatcher oc -n eventing-kafka-broker rollout restart deployment/kafka-broker-receiver
```

<!-- page break -->

Die Zustellung lief nach sechs Minuten wieder an; angenommene Ereignisse waren nicht betroffen, weil sie in Kafka persistiert waren.

##### Hauptursache

Die Reihenfolge in SOP-6 war nicht eingehalten: Das Truststore-Bundle wurde erst nach dem Serverzertifikat verteilt. SOP-6 wurde daraufhin um eine ausdrückliche Vorbedingung ergänzt (Kapitel 5.8).

##### Schritte zur Nachbildung

In ocp-di das Truststore-ConfigMap durch ein Bundle ohne die Issuing CA 3 ersetzen und den Dispatcher neu starten.

#### 6.3.3 Trigger stellt nicht zu, Filter greift nicht

##### Umgebung

Test und Produktion, nach Änderung eines Ereignistyps durch einen Bedarfsträger; Vorgang ESSUP-1533.

##### Fehlerbeschreibung

Der Produzent erhält HTTP 202, der Konsument erhält nichts. Der Trigger ist im Zustand Ready=True , die Metrik event_count zählt für diesen Trigger null Zustellungen. Im Protokoll des Filters keine Fehlermeldung, weil das Ereignis korrekt verworfen wird:

```
oc -n eventing-kafka-broker logs deploy/mt-broker-filter --tail=50 \ | grep -i "event not matching" {"msg":"event did not match trigger filter","trigger":"dd-archiv-events", "ce-type":"dd.dokument.archiviert.v2"}
```

##### Lösung

Filterausdruck des Triggers an den neuen Ereignistyp anpassen, Änderung in es-config einbringen und per ArgoCD ausrollen. Zusätzlich wurde der Bedarfsträger auf die Regel hingewiesen, dass eine neue Hauptversion eines Ereignistyps als Änderungsantrag zu melden ist (SOP-4).

##### Hauptursache

Der Produzent hatte ce-type von …v1 auf …v2 geändert, ohne den Trigger anzupassen. Ein Filter, der nicht zutrifft, verwirft das Ereignis stillschweigend - das ist beabsichtigtes Verhalten.

##### Schritte zur Nachbildung

Testereignis mit abweichendem ce-type senden:

```
curl -i -X POST https://broker-ingress.apps.test.caas.bavd.intern/dd-test/dd-test-broker \ -H "Ce-Specversion: 1.0" -H "Ce-Type: dd.dokument.archiviert.v2" \ -H "Ce-Source: /test" -H "Ce-Id: probe-001" -H "Content-Type: application/json" \ -d '{"ref":"dok-2026-4711"}'
```

#### 6.3.4 Dead-Letter-Topic füllt sich nach Umzug eines Konsumenten

##### Umgebung

Produktion, nach Umzug eines Konsumenten in einen neuen Namespace; Vorgang ESSUP-1560.

##### Fehlerbeschreibung

Der Alert DeadLetterMessagesPresent meldet innerhalb einer Stunde 1 240 Ereignisse im Topic …-dlq . Der Dispatcher protokolliert no such host :

```
{"level":"error","msg":"delivery failed after 5 attempts", "target":"http://notify.notify-prod.svc.cluster.local:8080", "error":"dial tcp: lookup notify.notify-prod.svc.cluster.local: no such host"}
```

<!-- page break -->

Zieladresse des Triggers auf den neuen Namespace korrigieren, ausrollen, Zustellung prüfen und die 1 240 Ereignisse nach Abstimmung mit dem Bedarfsträger mit es-utilities/dlq-replay erneut einstellen. Der Konsument bestätigte die idempotente Verarbeitung, sodass Duplikate unschädlich waren.

##### Hauptursache

Der Umzug des Konsumenten war nicht als Änderungsantrag gemeldet; die Trigger-Definition zeigte weiter auf den alten Dienstnamen.

##### Schritte zur Nachbildung

Zieladresse eines Triggers in ocp-test auf einen nicht existierenden Dienst setzen und 50 Ereignisse einspielen.

#### 6.3.5 Dispatcher startet nach einem Update nicht (CrashLoopBackOff)

##### Umgebung

Test, unmittelbar nach dem Wechsel auf OpenShift Serverless 1.36; Vorgang ESSUP-1602.

##### Fehlerbeschreibung

Zwei von drei Replikas des StatefulSets kafka-broker-dispatcher bleiben in CrashLoopBackOff . Im Protokoll:

```
FATAL failed to claim partitions for group knative-trigger-task-events: kafka server: The group member's supported protocols are incompatible with those of
```

```
existing members or first group member tried to join with empty protocol type
```

##### Lösung

Die alte Consumer-Gruppe war nach dem Update inkompatibel. Nach Abstimmung mit dem Dienstleister wurde das StatefulSet auf null skaliert, die Consumer-Gruppe entfernt und neu aufgebaut; die Offsets wurden auf den letzten festgeschriebenen Stand gesetzt, sodass keine Ereignisse verloren gingen:

```
oc -n eventing-kafka-broker scale statefulset kafka-broker-dispatcher --replicas=0 # durch Talwerk IT-Services auf kafka-t01: kafka-consumer-groups.sh --bootstrap-server kafka-t01.mw.bavd.intern:9093 \ --command-config /etc/kafka/client.properties \ --group knative-trigger-task-events --describe oc -n eventing-kafka-broker scale statefulset kafka-broker-dispatcher --replicas=3
```

##### Hauptursache

Wechsel des Zuweisungsverfahrens für Partitionen zwischen den Versionen. Der Fall trat nur auf, weil in ocptest alte Consumer-Gruppen aus einem früheren Versuch bestanden. Die Prüfung dieses Punktes ist seither Teil der Vorabprüfung auf ocp-di (Kapitel 5.4, Schritt 3).

##### Schritte zur Nachbildung

Auf ocp-di eine Consumer-Gruppe mit der Vorgängerversion anlegen, danach die neue Version ausrollen.

### 6.4 Incident-Liste

Die Incident-Liste ist die Historie der bearbeiteten Störungen. Sie dient dazu, ähnliche Fehler wiederzuerkennen und vorhandene Lösungswege erneut zu nutzen. Tabelle 28 gibt den Auszug des laufenden Jahres wieder; die vollständige Liste steht in Confluence unter display/PLT/Incident-Liste .

Tabelle 28: Incident-Liste (Auszug 2026)

Vorgang Datum Titel Ursache Dauer Maßnahme

<!-- page break -->

| Vorgang    | Datum      | Titel                                             | Ursache                                                     | Dauer      | Maßnahme                                                                                                                        |
|------------|------------|---------------------------------------------------|-------------------------------------------------------------|------------|---------------------------------------------------------------------------------------------------------------------------------|
| ESSUP-1482 | 07.05.2026 | Consumer-Lag über 5 000, Zustellung verzögert     | Konsument antwortete mit HTTP 503                           | 1 h 40 min | Behebung beim Konsumenten, Alert-Schwelle bestätigt                                                                             |
| ESSUP-1517 | 14.05.2026 | Zustellung nach CA-Wechsel unterbrochen           | neue Issuing-CA fehlte im Truststore                        | 42 min     | Truststore verteilt, SOP-6 um Vorbedingung ergänzt; Partnervorgänge ESSUP-1455 (Verteilauftrag) und ZSDSUP-0214 (BHB-PLT-0007)  |
| ESSUP-1533 | 28.05.2026 | Trigger stellt nicht zu                           | Ereignistyp ohne Änderungsantrag geändert                   | 3 h 10 min | Filter angepasst, Bedarfsträger nachgeschult                                                                                    |
| ESSUP-1560 | 18.06.2026 | 1 240 Ereignisse im Dead-Letter-Topic             | Konsument in neuen Namespace umgezogen                      | 2 h 05 min | Trigger korrigiert, Ereignisse erneut eingestellt                                                                               |
| ESSUP-1588 | 24.06.2026 | Kurzzeitige Nichtverfügbarkeit des Broker-Ingress | Wartung am Ingress-Router der Plattform ohne Vorankündigung | 11 min     | Abstimmung der Wartungsfenster mit dem CaaS-Team verschärft (10 Arbeitstage Vorlauf); Partnervorgang CAASUP-0342 (BHB-PLT-0001) |
| ESSUP-1602 | 02.07.2026 | Dispatcher in CrashLoopBackOff nach Update (Test) | inkompatible Consumer-Gruppe nach Versionswechsel           | 4 h 25 min | Gruppe neu aufgebaut, Prüfschritt in SOP-1 aufgenommen                                                                          |
| ESSUP-1641 | 16.07.2026 | Unterreplizierte Partitionen nach Broker-Neustart | Neustart zweier Broker in zu kurzem Abstand                 | 28 min     | Mindestabstand von zehn Minuten in SOP-6 festgeschrieben                                                                        |

### 6.5 Weitere Hinweise

- Unterschiede zwischen OpenShift- und Upstream-Ressourcen: Nicht jede Upstream-Anleitung passt auf die hier eingesetzte Distribution. Der Vergleich steht in Confluence unter display/PLT/Ressourcenvergleich und ist vor jedem Versionswechsel zu prüfen.
- Ergebnis der Duplikatstests: Bei einem Neustart des Dispatchers können Ereignisse erneut zugestellt werden. Die gemessene Duplikatrate lag bei 0,7 % der Ereignisse im Neustartfenster. Konsumenten müssen deshalb idempotent verarbeiten (Kapitel 4.3).
- Zonenkonzept: Für Fragen zum Zonenübergang West ⇄ Süd ist das Dokument NET-ZK-007 maßgeblich, nicht die Portmatrix dieses Handbuchs.
- Fremdursachen: Erfahrungsgemäß liegt bei etwa der Hälfte der gemeldeten Störungen die Ursache nicht im Event-System, sondern beim Konsumenten oder in der Konfiguration des Bedarfsträgers. Die Prüfreihenfolge in Kapitel 6.2 ist deshalb strikt einzuhalten.

<!-- page break -->

| Metrik                                       | Bedeutung                               | Schwellwert           | Alert                     |
|----------------------------------------------|-----------------------------------------|-----------------------|---------------------------|
|                                              | Ereignisse je Trigger                   | Ereignisse je Trigger |                           |
| event_count{result="error"}                  | fehlgeschlagene Zustellungen            | > 1 % über 5 min      | EventDeliveryErrorRate    |
| event_dispatch_latency_p95                   | Zustelldauer Dispatcher bis Zieladresse | > 500 ms über 10 min  | EventDispatchSlow         |
| kafka_consumergroup_lag                      | Rückstand je Consumer-Gruppe            | > 5 000 Nachrichten   | KafkaConsumerLag          |
| kafka_under_replicated_partitions            | unterreplizierte Partitionen            | > 0 über 5 min        | KafkaUnderReplicated      |
| heartbeat_missing_total                      | ausgefallene Heartbeat-Ereignisse       | > 2 über 10 min       | EventSystemHeartbeatLost  |
| dlq_messages_total                           | Bestand in den Dead-Letter-Topics       | > 0                   | DeadLetterMessagesPresent |
| certmanager_certificate_expiration_timestamp | Restlaufzeit der Zertifikate            | < 30 / 14 / 7 Tage    | TLSCertExpirySoon         |
| kube_pod_container_status_restarts_total     | Neustarts der Komponenten               | > 3 in 15 min         | EventSystemPodFlapping    |
| kafka_broker_disk_usage_ratio                | Belegung der Broker-Datenträger         | > 75 %                | KafkaDiskFilling          |

Tabelle 30 ordnet den Alerts Schweregrad und Meldeweg zu. Insgesamt sind zwölf Alarmregeln in drei Schweregraden hinterlegt.

Tabelle 30: Alarmierung

| Alert                     |   Schweregrad | Meldeweg                                     | Erste Maßnahme                                |
|---------------------------|---------------|----------------------------------------------|-----------------------------------------------|
| EventSystemHeartbeatLost  |             1 | Mattermost, E-Mail, Rufbereitschaft          | Prüfreihenfolge Kapitel 6.2                   |
| KafkaUnderReplicated      |             1 | Mattermost, E-Mail, Rufbereitschaft, Talwerk | Broker-Zustand beim Dienstleister erfragen    |
| EventDeliveryErrorRate    |             2 | Mattermost, E-Mail                           | betroffenen Trigger und Konsumenten bestimmen |
| KafkaConsumerLag          |             2 | Mattermost, E-Mail                           | Antwortverhalten des Konsumenten prüfen       |
| EventDispatchSlow         |             2 | Mattermost                                   | Traces in Tempo auswerten                     |
| TLSCertExpirySoon         |             3 | Mattermost, Vorgang                          | SOP-6 auslösen (Kapitel 5.8)                  |
| DeadLetterMessagesPresent |             3 | Mattermost                                   | Bestand aufarbeiten (wöchentliche Tätigkeit)  |
| KafkaDiskFilling          |             3 | E-Mail, Talwerk                              | Aufbewahrung und Kapazität prüfen             |

### 7.3 Protokolle

Die Komponenten schreiben strukturiert nach stdout und stderr . Der ClusterLogForwarder der Plattform übernimmt die Ströme, filtert sie je Namespace und legt sie in Loki ab. Ein Zugriff auf Knoten oder Container ist für die Protokollauswertung nicht erforderlich. Tabelle 31 nennt die Quellen.

<!-- page break -->

Tabelle 31: Protokollquellen und Aufbewahrung

| Quelle                          | Inhalt                                      | Ort                                          | Aufbewahrung   |
|---------------------------------|---------------------------------------------|----------------------------------------------|----------------|
| kafka-broker-receiver           | Annahme, Ablehnungen, Producer-Fehler       | Loki, Label app=kafka-broker-receiver        | 30 Tage        |
| kafka-broker-dispatcher         | Zustellversuche, Antwortcodes, Dead-Letter  | Loki                                         | 30 Tage        |
| mt-broker-filter                | Filterentscheidungen, verworfene Ereignisse | Loki                                         | 30 Tage        |
| eventing-controller             | Reconciliation, Zustand der Ressourcen      | Loki                                         | 30 Tage        |
| Kafka-Broker                    | Broker-Protokolle, ISR-Wechsel              | beim Dienstleister, Auszüge auf Anforderung  | 90 Tage        |
| Audit-Protokoll der Cluster-API | administrative Zugriffe                     | Plattform-Protokollierung der CaaS-Plattform | 180 Tage       |

Ein Protokolleintrag enthält immer die Ereigniskennung und die Trace-Kennung, sodass sich Protokoll und Trace verbinden lassen. Typische Abfragen:

```
# alle fehlgeschlagenen Zustellungen eines Triggers der letzten Stunde {namespace="eventing-kafka-broker", app="kafka-broker-dispatcher"} |= "delivery failed" | json | trigger="dd-archiv-events" # Weg eines einzelnen Ereignisses über alle Komponenten {namespace=~"knative-eventing|eventing-kafka-broker"} |= "b7f1c4e2"
```

### 7.4 Tracing mit Tempo

Tempo wird als verteiltes Tracing-System eingesetzt, um Abläufe in eventgetriebenen Architekturen Ende zu

Ende nachvollziehbar zu machen. Im Kontext des Event-System dient es dazu, Nachrichtenflüsse, Zustellungen und Latenzen zwischen den Komponenten sichtbar zu machen. Über die von Knative gesetzten Trace-Header lassen sich Ereignisse entlang der gesamten Verarbeitungskette korrelieren; Tempo speichert die Traces und erlaubt die Analyse in Verbindung mit Grafana. Damit lassen sich Fehlerursachen, verzögerte Zustellungen und fehlerhafte Trigger schnell eingrenzen.

Das Tracing wird überwiegend zur Fehlersuche genutzt. Die Abtastrate beträgt 10 %; bei einer laufenden Störung kann sie über den OTel-Collector zeitweise auf 100 % erhöht werden. Traces sind über die OpenShiftKonsole (Observe → Tracing) sowie in Grafana über die Datenquelle Tempo erreichbar. Die Aufbewahrung beträgt sieben Tage.

#### Gut zu wissen

Ein Trace endet nicht am Event-System: Setzt der Konsument den Header traceparent fort, ist der gesamte Weg vom Produzenten bis in das Zielsystem in einer Ansicht sichtbar. Bedarfsträger werden im Onboarding darauf hingewiesen (SOP-5).

<!-- page break -->

## 8 Datensicherung, Wiederherstellung und Notfallplan

### 8.1 Grundsatz

Das Event-System hält keine eigenen Fachdaten. Gesichert werden deshalb Konfiguration und Geheimnisse, nicht die Ereignisse selbst. Die Verfügbarkeit der Ereignisse innerhalb der Aufbewahrungsfrist wird über die Kafka-Replikation gewährleistet; daraus ergibt sich der RPO von 15 Minuten, der dem maximalen Rückstand zwischen den Replikaten unter Volllast entspricht.

Tabelle 32: Sicherungsobjekte und Verfahren

| Objekt                                                    | Verfahren                                                 | Turnus                                   | Ziel und Aufbewahrung                   |
|-----------------------------------------------------------|-----------------------------------------------------------|------------------------------------------|-----------------------------------------|
| Konfiguration (Broker, Trigger, Operatoren, Wertedateien) | Versionierung in Git, Spiegelung in das Backup-Repository | bei jeder Änderung, Spiegelung nächtlich | Git-Server und Commvault, 90 Tage       |
| Dashboards und Alarmregeln                                | Export als JSON in es-config                              | bei jeder Änderung                       | Git, unbegrenzt                         |
| Geheimnisse                                               | Vault-Snapshot durch das Plattformteam                    | täglich 23:30                            | Commvault, 30 Tage                      |
| Ereignisse in Kafka                                       | Replikation über drei Broker (RF 3, ISR 2)                | laufend                                  | keine Sicherung, Aufbewahrung 7 Tage    |
| Metriken, Protokolle, Traces                              | Objektspeicher der Plattform                              | laufend                                  | 90 / 30 / 7 Tage                        |
| Dokumentation und SOPs                                    | Confluence-Sicherung der Plattform                        | täglich                                  | Vorhaltung durch den Confluence-Betrieb |

### 8.2 Wiederherstellung

Die Wiederherstellung einer Stage erfolgt nicht durch Zurückspielen von Daten, sondern durch erneutes Ausrollen aus Git. Der Ablauf entspricht der Ersteinrichtung (Kapitel 5.3) und dauert erfahrungsgemäß 45 bis 60 Minuten je Stage:

1. Cluster-Verfügbarkeit mit dem CaaS-Plattformbetrieb klären.
2. ArgoCD-Applications es-<stage>-base und es-<stage>-config synchronisieren.
3. Kafka-Zugangsdaten aus Vault wiederherstellen und Verbindung prüfen.
4. Consumer-Gruppen prüfen; Offsets bleiben in Kafka erhalten, sodass die Verarbeitung an der letzten festgeschriebenen Position fortsetzt.
5. Funktionalen Test ausführen, Ergebnis im Vorgang dokumentieren.
6. Bedarfsträger über die Wiederaufnahme informieren.

#### Hinweis

Ereignisse, die während des Ausfalls nicht angenommen werden konnten, werden nicht nachträglich erzeugt. Das Nachliefern liegt beim Produzenten und ist Teil der Onboarding-Vereinbarung (SOP-5). Bereits angenommene Ereignisse gehen nicht verloren, solange die Aufbewahrungsfrist von sieben Tagen nicht überschritten wird.

### 8.3 Disaster Recovery

Tabelle 33 beschreibt die geplanten Ausfallszenarien mit ihren Auswirkungen und dem vorgesehenen Vorgehen.

<!-- page break -->

Tabelle 33: Ausfallszenarien

| Szenario                                                | Auswirkung                                                        | Vorgehen                                                                                                              | Zielzeit                 |
|---------------------------------------------------------|-------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|--------------------------|
| Ausfall eines Pods oder Knotens                         | keine, Lastverteilung greift                                      | automatischer Neustart durch die Plattform                                                                            | < 2 min                  |
| Ausfall eines Brandabschnitts in der Metro-Region West  | keine Unterbrechung; halbe Kapazität, erhöhte Latenz              | Aktiv-Aktiv-Betrieb, etcd-Quorum über drei Master; Kapazität mit dem CaaS-Team nachziehen                             | < 5 min                  |
| Ausfall eines Kafka-Brokers                             | keine, Replikationsfaktor 3                                       | Wiederherstellung durch den Dienstleister, ISR beobachten                                                             | < 30 min                 |
| Ausfall zweier Kafka-Broker                             | Annahme schlägt fehl (ISR unter 2), Produzenten erhalten HTTP 503 | Schweregrad 1, Talwerk IT-Services eskalieren, Bedarfsträger zum Puffern auffordern                                   | 4 h (RTO)                |
| Ausfall der Verbindung Metro-Region West ⇄ Hausnetz Süd | Zustellung steht vollständig, Ereignisse bleiben in Kafka         | Schweregrad 1, Netzbetrieb (Frank Dettmer) und ZRB einbeziehen                                                        | 4 h (RTO)                |
| Verlust eines vollständigen Clusters                    | Stage nicht verfügbar; Produktion: keine Zustellung               | Neuaufbau aus Git nach Kapitel 8.2, nach Wiederherstellung des Clusters durch das CaaS-Team                           | 4 h nach Clusterfreigabe |
| Verlust der Kafka-Daten                                 | nicht zugestellte Ereignisse sind endgültig verloren              | Bedarfsträger informieren, Nachlieferung durch die Produzenten anstoßen                                               | abhängig vom Verfahren   |
| Kompromittierung von Zugangsdaten                       | Vertraulichkeit betroffen                                         | SCRAM-Zugangsdaten und Zertifikate sofort tauschen (SOP-6, SOP-7), Meldung an den Informationssicherheitsbeauftragten | unverzüglich             |

### 8.4 Notfallplan

Bei einem Notfall - Vollausfall der Produktion über mehr als eine Stunde oder Verdacht auf eine Kompromittierung - gilt:

1. Störung mit Schweregrad 1 in ESSUP anlegen und im Kanal #event-system ankündigen.
2. Produktverantwortlichen (Tobias Reinhardt) und Bereichsleitung (Dr. Martina Kellerhoff) unverzüglich informieren; die Kommunikation an die Bedarfsträger ist inhaltlich vorab mit der Bereichsleitung abzustimmen.
3. Bei Beteiligung mehrerer Systeme eine Arbeitsgruppe im Kreis der betroffenen Systeme koordinieren und dafür einen eigenen Mattermost-Kanal anlegen.
4. Talwerk IT-Services GmbH über den Service Manager (Holger Pietsch) einbeziehen, wenn Kafka betroffen ist; Rufbereitschaft ist rund um die Uhr vereinbart.
5. Bedarfsträger auffordern, das Senden zu puffern, und die erwartete Dauer nennen.
6. Nach Behebung: Nachbetrachtung innerhalb von fünf Arbeitstagen, Aufnahme in die Incident-Liste, Prüfung der SOPs auf Anpassungsbedarf.

Die übergreifenden Meldewege und der Krisenstab sind im Notfallhandbuch des Bereichs IT-B ( NFH-ITB-2.1 ) geregelt.

### 8.5 Nachweise und Übungen

Tabelle 34: Nachweise und Übungen

| Nachweis   | Turnus   | Verantwortlich   | Letzte Durchführung   |
|------------|----------|------------------|-----------------------|

<!-- page break -->

| Nachweis                                                  | Turnus       | Verantwortlich        | Letzte Durchführung                  |
|-----------------------------------------------------------|--------------|-----------------------|--------------------------------------|
| Wiederaufbau einer Stage aus Git (Reinstallationstest)    | halbjährlich | Team Plattformdienste | Dev-Intern, 05.06.2026, 52 min       |
| Ausfall eines Kafka-Brokers (angekündigt)                 | halbjährlich | Talwerk IT-Services   | Test, 12.03.2026, ohne Auswirkung    |
| Wiederherstellung eines Vault-Snapshots                   | jährlich     | CaaS-Plattformbetrieb | 28.04.2026, erfolgreich              |
| Notfallübung mit Bedarfsträgern (Puffern und Nachliefern) | jährlich     | Nadine Schäfer        | 19.02.2026, zwei Verfahren beteiligt |

<!-- page break -->

## 9 Testfälle

### 9.1 Testarten

Tabelle 35 nennt die eingesetzten Testarten. Der Quellcode aller Tests liegt im Repository es-utilities ; Ergebnisse werden in Confluence unter display/PLT/Tests abgelegt.

Tabelle 35: Testarten

| Testart             | Umfang                                                                        | Werkzeug                         | Turnus                              | Letztes Ergebnis                                 |
|---------------------|-------------------------------------------------------------------------------|----------------------------------|-------------------------------------|--------------------------------------------------|
| Funktionaler Test   | je Broker ein Testereignis senden und die Zustellung an eine Testsenke prüfen | Go ( eventcheck )                | wöchentlich und nach jeder Änderung | 22.07.2026, alle Stages bestanden                |
| Duplikatstest       | Neustart des Dispatchers unter Last, Zählung mehrfach zugestellter Ereignisse | Go, Auswertung in Grafana        | vor jedem Versionswechsel           | 08.07.2026, Duplikatrate 0,7 %                   |
| Systemtest          | Zusammenspiel mit zwei Bedarfsträgern in der Testumgebung, Ende-zu-Ende       | manuell nach Testplan            | vor jedem Hauptrelease              | 10.07.2026, bestanden                            |
| Lasttest            | Lastprofil mit 1 000 Ereignissen je Sekunde über 30 Minuten                   | Hyperfoil                        | jährlich und vor Hauptreleases      | 11.07.2026, p95 = 210 ms bei 1 000 Ereignissen/s |
| Reinstallationstest | vollständiger Neuaufbau einer Stage aus Git                                   | ArgoCD, SOP-1 bis SOP-3          | halbjährlich                        | 05.06.2026, 52 Minuten                           |
| Notfalltest         | Ausfall eines Kafka-Brokers, Verhalten der Zustellung                         | abgestimmt mit dem Dienstleister | halbjährlich                        | 12.03.2026, keine Auswirkung                     |

### 9.2 Konkrete Testfälle

Tabelle 36 nennt die Testfälle, die bei jedem Versionswechsel abzuarbeiten sind. Der Nachweis erfolgt im Testprotokoll des jeweiligen Releases.

Tabelle 36: Testfälle für den Versionswechsel

| ID       | Testfall                                              | Erwartetes Ergebnis                                             |
|----------|-------------------------------------------------------|-----------------------------------------------------------------|
| TF-EG-01 | Ereignis an einen Kafka-Broker senden                 | HTTP 202, Ereignis im Topic, Zustellung an die Testsenke        |
| TF-EG-02 | Ereignis ohne ce-type senden                          | HTTP 400, kein Eintrag im Topic                                 |
| TF-EG-03 | Ereignis mit Rumpf über 64 KiB senden                 | HTTP 413, Ablehnung protokolliert                               |
| TF-EG-04 | Trigger mit nicht zutreffendem Filter                 | keine Zustellung, Ereignis verworfen, keine Fehlermeldung       |
| TF-EG-05 | Konsument antwortet dauerhaft mit HTTP 503            | fünf Zustellversuche, danach Ablage im Dead-Letter-Topic        |
| TF-EG-06 | Konsument antwortet beim dritten Versuch mit HTTP 200 | Zustellung gilt als erfolgreich, kein Dead-Letter               |
| TF-EG-07 | Neustart des Dispatchers unter Last                   | keine verlorenen Ereignisse, Duplikatrate unter 1 %             |
| TF-EG-08 | Ausfall eines Kafka-Brokers während der Annahme       | Annahme läuft weiter, ISR sinkt auf 2, kein Ereignisverlust     |
| TF-EG-09 | Zwei Ereignisse mit gleichem ce-subject               | Reihenfolge bleibt erhalten (gleiche Partition)                 |
| TF-EG-10 | Erneutes Einstellen aus dem Dead-Letter-Topic         | Ereignisse werden zugestellt, Zählerstände stimmen              |
| TF-EG-11 | Trigger-Zieladresse mit abgelaufenem Zertifikat       | Zustellung schlägt fehl, Protokolleintrag mit Zertifikatsfehler |
| TF-EG-12 | Trace über Produzent, Event-System und Konsument      | ein Trace mit allen Spannen in Tempo auffindbar                 |

<!-- page break -->

## 10 Rollen und Verantwortlichkeiten

### 10.1 Rollenübersicht

Rollen und Verantwortlichkeiten für einzelne Maßnahmen sind der jeweiligen SOP zu entnehmen. Tabelle 37 nennt die allgemeinen Verantwortlichkeiten.

Tabelle 37: Rollen und Verantwortlichkeiten

| Rolle                         | Person                                    | Umfang                                                                                                                |
|-------------------------------|-------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| Produktverantwortung          | Tobias Reinhardt (Bereich IT-B 2)         | Gesamtverantwortung, Freigaben, Kommunikation mit Bedarfsträgern und Bereichsleitung, Fortschreibung dieses Handbuchs |
| Vertretung                    | Nadine Schäfer                            | vollumfängliche Vertretung, zusätzlich Onboarding der Bedarfsträger                                                   |
| Betrieb Kafka-Anbindung, SRE  | Jonas Brinkmann                           | Kafka-Anbindung, Zertifikate, Kapazitätsplanung, Abstimmung mit dem Dienstleister                                     |
| Entwicklung und Observability | Miriam Falk                               | Weiterentwicklung, Dashboards, Alarmregeln, Lasttests                                                                 |
| Koordination First Level      | Sven Lorenz                               | Besetzung des Betriebskalenders, Dead-Letter-Aufarbeitung, Erstbewertung                                              |
| Plattformbetrieb              | Andreas Wehrle (Team CaaS)                | Cluster, Ingress, Service Mesh, Speicherklassen, Pull-Request-Freigaben                                               |
| Kafka-Betrieb                 | Holger Pietsch (Talwerk IT-Services GmbH) | Broker, Topics, ACLs, Keystores, Kapazität                                                                            |
| Netzbetrieb                   | Frank Dettmer                             | Firewall-Freischaltungen, Zonenübergänge                                                                              |
| PKI-Betrieb                   | Sabine Wollmer                            | Ausstellung und Widerruf von Zertifikaten, Betrieb der ausstellenden CA                                               |
| IAM-Betrieb                   | Kai Ostermann                             | Realm, Gruppen, OIDC-Clients                                                                                          |
| Bereichsleitung               | Dr. Martina Kellerhoff                    | Eskalationsstufe 2, Freigabe der Kommunikation bei Major Incidents                                                    |

### 10.2 Supportlevel

Formale Support- oder Servicelevel werden zwischen dem Team Plattformdienste und seinen Bedarfsträgern nicht vereinbart; maßgeblich sind der Servicekatalog ( SK-PLT-1.9 ) und die Angaben in Kapitel 3.5 und 5.1. Tabelle 38 beschreibt die Aufgabenteilung.

Tabelle 38: Supportlevel

| Level                  | Wer                                                | Aufgaben                                                                                                                                  |
|------------------------|----------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------|
| 1st Level              | Team Plattformdienste nach Betriebskalender        | Annahme über Jira, Mattermost und Postfach, Erstbewertung, Behebung fehlerhafter Konfigurationen, Terminvereinbarung für tiefere Analysen |
| 2nd Level              | Team Plattformdienste (fachlich zuständige Person) | Analyse anhand von Metriken, Protokollen und Traces, Änderungen an Broker- und Trigger-Konfiguration                                      |
| 3rd Level Event-System | Team Plattformdienste (Entwicklung)                | Problem-Management, Korrekturen an Konfiguration und eigenen Komponenten, Herstellerkontakt über den OpenShift-Support                    |

<!-- page break -->

| Level               | Wer                        | Aufgaben                                                                          |
|---------------------|----------------------------|-----------------------------------------------------------------------------------|
| 3rd Level Kafka     | Talwerk IT-Services GmbH   | Störungen der Broker, Topics, ACLs und Keystores; Rufbereitschaft rund um die Uhr |
| 3rd Level Plattform | Team CaaS-Plattformbetrieb | Cluster, Knoten, Ingress, Service Mesh, Speicher                                  |

### 10.3 Dienstleister

Tabelle 39: Beteiligte Dienstleister

| Firma                                    | Leistung                                                 | Vertrag           | Servicezeit                             | Kontakt                                        |
|------------------------------------------|----------------------------------------------------------|-------------------|-----------------------------------------|------------------------------------------------|
| Talwerk IT-Services GmbH                 | Betrieb Apache Kafka, 3rd Level                          | RV-2024-0817      | Mo-Fr 07:00-19:00, Rufbereitschaft 24/7 | Holger Pietsch, kafka-service@rheinwerk-its.de |
| Red Hat                                  | Subskription und Support OpenShift Container Platform    | SUB-OCP-4471-BAVD | 24/7 Premium                            | über den OpenShift-Support des CaaS-Teams      |
| ZRB - Zentrales Rechenzentrum des Bundes | Rechenzentrums- und Netzleistungen, Serviceklasse Bronze | LS-ZRB-2022-5210  | nach Serviceklasse                      | über den Servicedesk 0800 1180 100             |

### 10.4 Eskalationsweg

Bei Major Incidents sind die Bereichsleitung und die Bedarfsträger zeitnah zu informieren. Die Kommunikation in Richtung der Bedarfsträger muss inhaltlich vorab mit der Bereichsleitung abgestimmt sein. Die Koordinierung einer Arbeitsgruppe erfolgt im Kreis der beteiligten Systeme; es hat sich bewährt, dafür einen eigenen Mattermost-Kanal anzulegen.

Tabelle 40: Eskalationsstufen

|   Stufe | Auslöser                                                                                                       | Adressat                                                                                          | Frist            |
|---------|----------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|------------------|
|       1 | Störung nicht innerhalb der zugesagten Zeit angenommen oder Lösungsweg unklar                                  | Produktverantwortlicher (Tobias Reinhardt), Vertretung (Nadine Schäfer)                           | sofort           |
|       2 | Vollausfall der Produktion über eine Stunde, mehrere Verfahren betroffen                                       | Bereichsleitung IT-B (Dr. Martina Kellerhoff)                                                     | innerhalb 30 min |
|       3 | Vollausfall über vier Stunden, Verdacht auf Kompromittierung, absehbare Fristverletzung in einem Fachverfahren | Krisenstab nach Notfallhandbuch NFH-ITB-2.1 , Informationssicherheits- und Datenschutzbeauftragte | unverzüglich     |

### 10.5 RACI-Matrix

Tabelle 41 ordnet die Arbeitsschritte der SOPs den Beteiligten zu. R = Responsible (zuständig für die Durchführung), A = Accountable (Verantwortung aus Budgetsicht), C = Consulted (verfügt über sachdienliche Informationen), I = Informed (erhält Information über Tätigkeit oder Ergebnis).

Tabelle 41: RACI-Matrix über die SOPs

| SOP   | Arbeitsschritt                                | Plattform­ dienste   | Bedarfs­ träger   | CaaS   | Talwerk   | ZRB   |
|-------|-----------------------------------------------|----------------------|-------------------|--------|-----------|-------|
| SOP-1 | Fork mit dem Upstream synchronisieren         | R, A                 | -                 | C      | -         | -     |
| SOP-1 | Temporären Branch anlegen, Änderung vornehmen | R, A                 | -                 | C      | -         | -     |