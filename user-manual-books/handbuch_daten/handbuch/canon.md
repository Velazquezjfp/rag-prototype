# Kanon der Testdaten — Betriebshandbücher (Mock-Daten)

Alle Personen, Hosts, IP-Adressen, URLs, Vorgangsnummern und Vertragsnummern in den
drei Betriebshandbüchern sind **frei erfunden**. Diese Datei ist die Referenz, gegen
die alle drei Dokumente geprüft wurden (Konsistenz innerhalb und zwischen Dokumenten).

Stand der Dokumente: Juli 2026.

---

## 1. Organisation und Standorte

| Element | Wert |
|---|---|
| Behörde | BAVD (Bundesamt für Verfahrensdienste) |
| Interne DNS-Zone | `bavd.intern` |
| Plattform | BDOP — Behördliche DevOps-Plattform (OpenShift), Subzone `bdop.bavd.intern` |
| Rechenzentrum West | Metro-Region West, zwei Brandabschnitte `WE-A` / `WE-B`, Aktiv-Aktiv |
| Rechenzentrum Süd | Hausnetz Süd (`NBG`), Middleware, IAM, GSLB |
| Infrastrukturdienstleister | ZRB (Serviceklasse Bronze) |
| Jumphost | `jump01.mgmt.bavd.intern` (SSH 22, nur aus ZONE-MGMT) |

### Netzzonen

| Zone | Beschreibung | Netz |
|---|---|---|
| ZONE-EXT | Behördennetz / Bundesnetz, Clientzugriff | — |
| ZONE-DMZ | Reverse Proxy, BEP-Gateway | `172.20.10.0/24` |
| ZONE-APP-WE | OpenShift Worker, Anwendungsserver West | `10.30.0.0/16` |
| ZONE-APP-SD | Middleware, IAM, GSLB Süd | `10.20.0.0/16` |
| ZONE-VERF | Verfahrensnetz (BUPP, Dokumentendienste VMs) | `10.40.0.0/16` |
| ZONE-DATA | Datenbank- und Storage-Netz | `10.40.30.0/23` |
| ZONE-MGMT | Administration, Jumphosts, Backup | `10.99.0.0/16` |

---

## 2. Personen

### 2.1 Dokumentübergreifend (bewusste Cross-Referenzen)

| Person | Rolle | Kontakt | In Dokument |
|---|---|---|---|
| Sabine Wollmer | PKI-Betrieb / Registrierungsstelle, Bereich IT-S 1 | pki@bavd.bund.de, Durchwahl 1180 | Event-System, Mars, BUPP |
| Frank Dettmer | Netzbetrieb, Firewall-Freischaltungen | netzbetrieb@bavd.bund.de, Durchwahl 1240 | Event-System, Mars, BUPP |
| Kai Ostermann | IAM-Betrieb (Keycloak, Active Directory) | iam-betrieb@bavd.bund.de, Durchwahl 1315 | Event-System (SSO Grafana), Mars, BUPP |
| Andreas Wehrle | Teamleiter BDOP-Plattformbetrieb | andreas.wehrle@bavd.bund.de, Durchwahl 2140 | Event-System, Mars |
| Petra Nowak | Datenbankbetrieb Oracle, Team DB-Services | db-services@bavd.bund.de, Durchwahl 1420 | Mars, BUPP |
| Dr. Martina Kellerhoff | Bereichsleitung IT-B (Eskalationsstufe 2) | Durchwahl 2100 | Event-System, Mars |

Bewusst **nicht** verbunden: BUPP nutzt das Event-System nicht (keine eventgetriebene
Anbindung); Event-System nutzt keine Oracle-Datenbank (kein Kontakt zu Petra Nowak
für Persistenz); BUPP läuft nicht auf der BDOP (kein Kontakt zu Andreas Wehrle).

### 2.2 Event-System 2.0 — Team Plattformdienste, Bereich IT-B 2

| Person | Rolle |
|---|---|
| Tobias Reinhardt | Produktverantwortlicher Event-System, Durchwahl 2117 |
| Nadine Schäfer | Vertreterin, Durchwahl 2119 |
| Jonas Brinkmann | Site Reliability Engineer, Schwerpunkt Kafka |
| Miriam Falk | Entwicklung, Schwerpunkt Observability |
| Sven Lorenz | Koordination First-Level-Support |
| Holger Pietsch | Service Manager, Talwerk IT-Services GmbH (Kafka-Betrieb) |

### 2.3 Mars Dokumentendienste — Bereich VF 3

| Person | Rolle |
|---|---|
| Christina Haberland | Produktverantwortliche Dokumentendienste, Durchwahl 3208 |
| Daniel Osterloh | Vertreter, Durchwahl 3211 |
| Rainer Kolbe | Systembetrieb Dokumentendienste |
| Elke Sandmann | Anwendungsbetreuung / 2nd Level |
| Lars Grünewald | Projektleitung, Steinbach Digital GmbH (Entwicklungspartner) |

### 2.4 BUPP — Bereich GF 4

| Person | Rolle |
|---|---|
| Heiko Brandtner | Produktverantwortlicher BUPP, Durchwahl 4471 |
| Yasmin Özdemir | Vertreterin, Durchwahl 4473 |
| Torben Machwitz | Systembetrieb BUPP |
| Anja Rothbauer | Anwendungsbetreuung / 2nd Level |
| Ulrike Mattern | Projektleitung, Kranich Software GmbH (Entwicklungspartner) |
| Dr. Ulrich Sammer | Bereichsleitung GF 4 (Eskalationsstufe 2) |

### 2.5 Dienstleister (fiktiv)

| Firma | Leistung | Vertrag | Servicezeit |
|---|---|---|---|
| Talwerk IT-Services GmbH | Betrieb Apache Kafka, 3rd Level | RV-2024-0817 | Mo–Fr 07:00–19:00, Rufbereitschaft 24/7 |
| Steinbach Digital GmbH | Entwicklung Dokumentendienste, 3rd Level | RV-2023-0442 | Mo–Fr 08:00–18:00 |
| Kranich Software GmbH | Entwicklung BUPP, 3rd Level | RV-2022-0913 | Mo–Fr 08:00–17:00 |
| Red Hat | OpenShift Container Platform Subscription | SUB-OCP-4471-BAVD | 24/7 Premium |

---

## 3. Gemeinsame Basisdienste

| Dienst | Endpunkt | Port | Genutzt von |
|---|---|---|---|
| Confluence | `https://confluence.bavd.intern` | 443 | alle |
| Jira | `https://jira.bavd.intern` | 443 | alle |
| Git (Bitbucket) | `https://git.bavd.intern` | 443 | alle |
| Mattermost | `https://chat.bavd.intern` | 443 | alle |
| IAM (Keycloak 24.0) | `https://iam.bavd.intern/realms/bavd-intern` | 443 | alle |
| Active Directory | `ad01.bavd.intern`, `ad02.bavd.intern` | 636 (LDAPS) | Mars, BUPP |
| Secret-Management (Vault) | `https://vault.bdop.bavd.intern` | 443 | alle |
| Interne PKI (RA-Portal) | `https://pki.bavd.intern/ra` | 443 | alle |
| ACME-Endpunkt der PKI | `https://pki.bavd.intern/acme/directory` | 443 | Event-System, Mars |
| Grafana (BDOP) | `https://grafana.bdop.bavd.intern` | 443 | Event-System, Mars |
| Checkmk (VM-Monitoring) | `https://checkmk.bavd.intern` | 443 | Mars, BUPP |
| OpenSearch Dashboards | `https://logs.bavd.intern` | 443 | BUPP |
| SMTP-Relay | `smtp.bavd.intern` | 25 | alle |
| Backup (Commvault) | `bkp01.mgmt.bavd.intern` | 8403 | Mars, BUPP |
| Artifact-Registry (Nexus) | `https://nexus.bavd.intern` | 443 | alle |

### PKI-Kanon (Grundlage für „Wie erneuere ich ein TLS-Zertifikat?")

| Element | Wert |
|---|---|
| Root-CA | `BAVD Root CA 2`, gültig 2019–2039 |
| Issuing-CA | `BAVD Issuing CA 3`, gültig 2023–2033 |
| Schlüssel | RSA 3072 Bit oder ECDSA P-256 |
| Zertifikatslaufzeit | 397 Tage |
| Erneuerung | ab 30 Tage vor Ablauf, spätestens 7 Tage vorher |
| Antrag | Jira-Projekt `PKI`, Vorgangstyp „Zertifikatsantrag" |
| Automatisiert | cert-manager 1.14, ClusterIssuer `bavd-issuing-ca-3` (nur BDOP) |
| Monitoring-Alert | `TLSCertExpirySoon` (30/14/7 Tage) |
| Ansprechpartnerin | Sabine Wollmer, pki@bavd.bund.de |

---

## 4. Event-System 2.0

| Element | Wert |
|---|---|
| Jira-Projekt | `ESSUP` (Beispielvorgänge `ESSUP-1482`, `ESSUP-1517`) |
| Mattermost | `https://chat.bavd.intern/bavd/channels/event-system` |
| Funktionspostfach | event-system@bavd.bund.de |
| CI-Nummer | `CI-PLT-0042` |
| Verfügbarkeit PROD | 99,97 % (Apr 2025 – Mär 2026), RTO 4 h, RPO 15 min |
| Betriebszeiten | 24/7; Servicezeiten Mo–Do 08:00–16:00, Fr 08:00–14:00 |
| Wartungsfenster | Mittwoch ab 17:00 |
| Schutzbedarf | Vertraulichkeit hoch, Integrität mittel, Verfügbarkeit hoch |

### OpenShift-Cluster

| Stage | Cluster | API-Endpunkt | Apps-Domain | Worker |
|---|---|---|---|---|
| Dev-Intern | `ocp-di` | `https://api.di.bdop.bavd.intern:6443` | `apps.di.bdop.bavd.intern` | 3 |
| Dev | `ocp-dev` | `https://api.dev.bdop.bavd.intern:6443` | `apps.dev.bdop.bavd.intern` | 6 |
| Test | `ocp-test` | `https://api.test.bdop.bavd.intern:6443` | `apps.test.bdop.bavd.intern` | 6 |
| Prod | `ocp-prod` | `https://api.prod.bdop.bavd.intern:6443` | `apps.prod.bdop.bavd.intern` | 12 |

Prod-VIPs: API `10.30.8.6`, Ingress `10.30.8.7`. Namespaces: `knative-eventing`,
`eventing-kafka-broker`, `event-system-ops`, `event-system-debug`.

### Kafka (Talwerk IT-Services, Hausnetz Süd)

| Stage | Broker | IP | Port |
|---|---|---|---|
| Dev | `kafka-d01/02/03.mw.bavd.intern` | 10.20.10.11–13 | 9093 (SASL_SSL) |
| Test | `kafka-t01/02/03.mw.bavd.intern` | 10.20.11.11–13 | 9093 |
| Prod | `kafka-p01/02/03.mw.bavd.intern` | 10.20.12.11–13 | 9093 |

Kafka 3.9.0 (KRaft), Replikationsfaktor 3, `min.insync.replicas=2`,
Retention 7 Tage, JMX-Exporter Port 9404, Topic-Präfix
`knative-broker-<namespace>-<broker>`.

### Versionen

OpenShift Container Platform 4.16 · OpenShift Serverless 1.36 (Knative Eventing 1.15) ·
Apache Kafka 3.9.0 · Quarkus 3.24 · ArgoCD 2.12 · cert-manager 1.14 · Grafana 11.3 ·
Tempo 2.6 · Loki 3.2 · Prometheus 2.54

### Angebundene Systeme

| System | Rolle | Anbindung |
|---|---|---|
| DTP — Datentransferplattform | Event-Produzent | HTTP POST an Broker-Ingress |
| Task-Manager | Event-Konsument | Trigger → HTTP |
| Mars Dokumentendienste | Produzent und Konsument | Trigger `dd-archiv-events` |
| Fachanwendungen (Bedarfsträger) | beides | projektspezifische Broker |

### SOPs

`SOP-1` Knative-Eventing-Konfiguration · `SOP-2` Global-Broker · `SOP-3`
Observability-Stack · `SOP-4` Kommunikation mit Bedarfsträgern · `SOP-5` Onboarding ·
`SOP-6` CA-Zertifikate erneuern · `SOP-7` Kafka-Topic-Bereinigung

---

## 5. Mars Dokumentendienste

| Element | Wert |
|---|---|
| Fachverfahren | Mars (Modulares Antrags- und Registrierungssystem) |
| Jira-Projekt | `DDSUP` (Beispiele `DDSUP-0917`, `DDSUP-1181`, `DDSUP-1206`) |
| Mattermost | `https://chat.bavd.intern/bavd/channels/dokumentendienste` |
| Funktionspostfach | dokumentendienste@bavd.bund.de |
| CI-Nummer | `CI-VRF-0118` |
| Verfügbarkeit | Ziel 99,5 % in Servicezeit; RTO 8 h, RPO 1 h |
| Betriebszeiten | Mo–Sa 06:00–22:00; Servicezeiten Mo–Fr 07:00–17:00 |
| Wartungsfenster | Dienstag 18:00–22:00 |
| Schutzbedarf | Vertraulichkeit hoch, Integrität hoch, Verfügbarkeit mittel |

### Komponenten (OpenShift, Namespace `dokumentendienste-prod` auf `ocp-prod`)

| Dienst | Route / Service | Port | Replikas |
|---|---|---|---|
| `dd-gateway` | `https://dd-gateway.apps.prod.bdop.bavd.intern` | 8443 | 3 |
| `dd-read-service` | `dd-read-service.dokumentendienste-prod.svc` | 8080 | 4 |
| `dd-write-service` | `dd-write-service…svc` | 8080 | 2 |
| `dd-metadata-service` | `dd-metadata-service…svc` | 8080 | 2 |
| `dd-ingest-worker` | kein Ingress | 8080 | 2–6 (HPA) |
| `dd-scan-service` (ClamAV) | `dd-scan-service…svc` | 3310 | 2 |
| `dd-ocr-service` (Tesseract) | `dd-ocr-service…svc` | 8080 | 2 |

### VMs

| Host | IP | Rolle |
|---|---|---|
| `dd-arch-p01.dd.bavd.intern` | 10.40.31.11 | Archiv-Adapter ArchivLine, Brandabschnitt WE-A |
| `dd-arch-p02.dd.bavd.intern` | 10.40.31.12 | Archiv-Adapter, WE-B |
| `dd-file-p01.dd.bavd.intern` | 10.40.31.21 | NFS-Gateway Ingest-Spool |
| `ora-dd-p01.db.bavd.intern` | 10.40.33.11 | Oracle 19c RAC Node 1 |
| `ora-dd-p02.db.bavd.intern` | 10.40.33.12 | Oracle 19c RAC Node 2 |
| `s3-dd-p01.db.bavd.intern` | 10.40.33.21 | Objektspeicher (MinIO), Bucket `dd-documents` |

Oracle: SCAN `ora-dd-scan.db.bavd.intern`, Port 1521 (TCP) / 2484 (TCPS),
Service `DDPROD01_SVC`, Schemata `DD_META`, `DD_AUDIT`.

### Quellsysteme und Ziele

Mars · ZPS (Zentrale Poststelle) · BEP-Gateway (`bep-gw-p01`, ZONE-DMZ) →
Dokumentendienste → Langzeitarchiv ArchivLine 2023.3 (`arch-al-p01.dd.bavd.intern`, 8443).
Ereignisse werden über das **Event-System** publiziert (Broker `dd-prod-broker`).

### Versionen

RHEL 9.4 · Red Hat build of OpenJDK 21.0.3 · Spring Boot 3.3.2 · Oracle 19c (19.24) ·
ClamAV 1.3.1 · Tesseract 5.3.4 · Apache Tika 2.9.2 · MinIO RELEASE.2024-06-04 ·
ArchivLine 2023.3

### SOPs

`SOP-DD-01` Ingest-Störung · `SOP-DD-02` Wiederherstellung Metadaten-DB ·
`SOP-DD-03` Archivabgleich · `SOP-DD-04` Release-Einspielung ·
`SOP-DD-05` TLS-Zertifikate erneuern · `SOP-DD-06` Notfallbetrieb Spool

---

## 6. BUPP — Unterstützungsportal für Prüfprozesse

| Element | Wert |
|---|---|
| Jira-Projekt | `BUPSUP` (Beispiel `BUPSUP-2244`) |
| Mattermost | `https://chat.bavd.intern/bavd/channels/bupp-betrieb` |
| Funktionspostfach | bupp-betrieb@bavd.bund.de |
| CI-Nummer | `CI-VRF-0207` |
| Verfügbarkeit | Ziel 99,8 %; RTO 4 h, RPO 30 min |
| Betriebszeiten | 24/7; Servicezeiten Mo–Fr 08:00–17:00 |
| Wartungsfenster | Donnerstag 17:00–21:00 |
| Schutzbedarf | Vertraulichkeit hoch, Integrität hoch, Verfügbarkeit hoch |
| Aktuelles Release | 1.2.3 (OpenJDK 17, Keycloak-Anbindung) |

### Umgebungen

| Stage | Frontend | Backend | Datenbank |
|---|---|---|---|
| Test | `bupp-web-t01/t02.bupp.bavd.intern` | `bupp-app-t01/t02.bupp.bavd.intern` | `ora-bupp-t01.db.bavd.intern:1547`, Service `BUPPRT01_SVC` |
| Abnahme (JDK 17) | `bupp-web-a01/a02` | `bupp-app-a01/a02` | `ora-bupp-a01.db.bavd.intern:1547`, Service `BUPPXA01_SVC` |
| Produktion (JDK 17) | `bupp-web-p01/p02` | `bupp-app-p01/p02` | RAC `ora-bupp-p01/p02.db.bavd.intern:1547`, Service `BUPPXP01_SVC` |

IPs Produktion: Web `10.40.21.11/12`, App `10.40.22.11/12`, DB `10.40.23.11/12`.
F5-VIP `bupp.bavd.intern` → `10.40.20.10`. IDM-Schema `IDM_BUPP` auf derselben
Instanz. Alt-Umgebung (JDK 11, OAM) wurde zum 31.03.2026 außer Betrieb genommen.

### Ports

443 (Client → F5) · 8443 (F5 → Webtier) · 8009 entfällt, 8443 mTLS (Webtier → Apptier) ·
1547 TCPS (Apptier → Oracle) · 5701–5703 (Hazelcast-Cluster) · 636 LDAPS ·
9100 Node-Exporter · 22 SSH nur vom Jumphost

### Versionen

RHEL 8.10 · Red Hat build of OpenJDK 17.0.11 · Apache Tomcat 10.1.24 ·
Spring Boot 3.2.5 · Hazelcast 5.3.6 · Apache HTTP Server 2.4.57 · Oracle 19c (19.24) ·
Keycloak 24.0 · Ansible Automation Platform 2.4 · F5 BIG-IP 17.1

### Dokumentierte Störungsbilder

1. `OAuth2AccessDeniedException: Error requesting access token` — Client-Secret rotiert
2. `UnsatisfiedDependencyException: httpClientConnectionManager` — Truststore ohne neue Issuing-CA
3. `HazelcastInstanceNotActiveException: State: SHUT_DOWN` — Split-Brain nach Netzwartung
4. `only supports upgrade via ALPN` — HTTP/2 ohne ALPN am Reverse Proxy
5. `ORA-12547: TNS lost contact` — Firewall-Idle-Timeout auf Port 1547

### SOPs

`SOP-BUPP-01` Release-Schwenk (Blue/Green) · `SOP-BUPP-02` Rollback ·
`SOP-BUPP-03` Stromabschaltung / geordnetes Stoppen · `SOP-BUPP-04` Datenbank-Restore ·
`SOP-BUPP-05` TLS-Keystore erneuern · `SOP-BUPP-06` Hazelcast-Cluster-Neustart

---

## 7. Bewusst gesetzte Konsistenz- und Abgrenzungsmerkmale

Für die Erprobung von Ontologie und Knowledge Graph:

1. **Geteilte Entitäten:** PKI/Issuing-CA, Keycloak-Realm, Vault, Jumphost, Netzbetrieb,
   Backupsystem, Jira/Confluence/Mattermost, ZRB-Serviceklasse.
2. **Geteilte Personen:** Sabine Wollmer (3 Dokumente), Frank Dettmer (3),
   Kai Ostermann (3), Andreas Wehrle (2), Petra Nowak (2), Dr. Kellerhoff (2).
3. **Echte fachliche Kopplung:** Mars Dokumentendienste publiziert Ereignisse über
   das Event-System (Broker `dd-prod-broker`, Trigger `dd-archiv-events`) — in beiden
   Dokumenten beschrieben, aus jeweils eigener Perspektive.
4. **Bewusste Nicht-Kopplung:** BUPP ist nicht an das Event-System angebunden und läuft
   nicht auf der BDOP; das Event-System nutzt keine Oracle-Datenbank.
5. **Unterschiedliche Lösungswege für dasselbe Problem:** TLS-Erneuerung erfolgt im
   Event-System vollautomatisch (cert-manager/ACME), bei den Dokumentendiensten
   gemischt (cert-manager für Routen, manuell für den Archiv-Adapter) und bei BUPP
   vollständig manuell (keytool, Ansible-Playbook).
6. **Widerspruchsfreie, aber unterschiedliche Kennzahlen:** je Dokument eigene
   Verfügbarkeits-, RTO/RPO- und Wartungsfensterwerte.

---

## 8. Ergänzungen aus den Diagrammen (nachträglich in den Kanon aufgenommen)

### BUPP

| Element | Wert |
|---|---|
| Reverse Proxy (ZONE-DMZ) | `bupp-rp-p01.dmz.bavd.intern` 172.20.10.21, `bupp-rp-p02` 172.20.10.22 |
| Firewall-Regeln | `FW-BUPP-001` … `FW-BUPP-012` |
| ZONE-MGMT | `jump01` 10.99.4.10, `checkmk` 10.99.6.20, `bkp01` 10.99.8.30 |
| Oracle | SCAN `ora-bupp-scan.db.bavd.intern`, Fachschema `BUPP_APP`, SGA 24 GB, ca. 1,8 TB |
| F5 | Pools `bupp-web-prod` / `bupp-web-prod-b`, Monitor `GET /bupp/health` (5 s), Erkennung ≤ 15 s |
| Stage-VIPs | `bupp-test.bavd.intern`, `bupp-abnahme.bavd.intern` |
| Releases | 1.2.3 produktiv, 1.2.4 Beispiel-Schwenk, 1.3.0-RC2 in Test |
| Keycloak-Client | `bupp-portal` (Authorization Code + PKCE) |
| Ansible | Playbooks `bupp-deploy`, `bupp-tls`, `bupp-secrets`; Repo `bupp-config` |
| Agenten | Checkmk-Agent TCP 6556, Filebeat 8.13 → OpenSearch |
| Firewall-Idle-Timeout | 60 min auf TCP 1547 (Ursache Störungsbild 5) |
| Sicherung | Voll So 01:00 (95 min), inkrementell Mo–Sa 01:00 (25 min), Archivelog alle 15 min, Commvault 22:00, Vault-Snapshot 23:00; Aufbewahrung 30 T Platte / 90 T Band |
| Restore | 6 Schritte = 4 h RTO; Restore Point `BUPP_R124`, Flashback-Bereich 400 GB, Liquibase < 8 min |
| Kennzahlen | Access-Token 5 min, Refresh 30 min, Tomcat-Session 30 min, HikariCP 20 Verbindungen |
| Abbruchkriterien Schwenk | Fehlerrate ≥ 0,5 % oder p95 ≥ 900 ms, Beobachtungsfenster 60 min, Change-Vorlauf 5 Arbeitstage |
| Pfade | `/opt/tomcat/webapps`, `/etc/httpd` |

### Mars Dokumentendienste

| Element | Wert |
|---|---|
| Langzeitarchiv | `arch-al-p01.dd.bavd.intern` 10.40.31.31 : 8443 |
| Firewall-Regeln | `FW-DD-001` … `FW-DD-014` |
| BEP-Gateway | `bep-gw-p01.dmz.bavd.intern` 172.20.10.31 |
| Spool | PVC `dd-spool-pvc` 500 GiB (RWX) über `dd-file-p01`, NFS 2049 |
| Datenbestand | 3,1 TB Metadaten, 38 TB Dokumente, 12,4 Mio. Dokumente |
| Trigger (eingehend) | `dd-task-events` (Filter `type = task.dokument.*`) |
| Ereignistypen | `dd.dokument.eingegangen.v1`, `dd.dokument.archiviert.v1`, `dd.stapel.abgeschlossen.v1`, `dd.fehler.virenfund.v1` |
| Schemamigration | Liquibase, Changelog im Repo `dd-config` |
| Sicherung | RMAN voll So 02:00, inkrementell täglich 02:00, Archivelog alle 30 min; MinIO-Bucket-Replikation nach WE-B; Commvault 23:00 |

### Nachträge aus dem Mars-Handbuch (verbindlich für alle Dokumente)

| Element | Wert |
|---|---|
| Test-/Dev-Hosts DD | `dd-arch-t01` 10.40.41.11, `arch-al-t01` 10.40.41.31, `dd-file-t01` 10.40.41.21, `ora-dd-t01` 10.40.43.11 (`DDTEST01_SVC`), `s3-dd-t01` 10.40.43.21 (Bucket `dd-documents-test`), `ora-dd-d01` 10.40.43.31 (`DDDEV01_SVC`) |
| Namespaces DD | `dokumentendienste-prod` / `-test` / `-dev`, Attrappe `dd-arch-mock` |
| Netze | ZONE-VERF Prod 10.40.31.0/24, Test 10.40.41.0/24; ZONE-DATA Prod 10.40.33.0/24, Test 10.40.43.0/24; Pod-Netz 10.128.0.0/14; Egress-IP 10.30.9.40; Firewall-Cluster FW-WE-01 / FW-WE-02 |
| DR | Objektspeicher-Zweitstandort `s3-dd-b01` (WE-B) |
| Release DD | produktiv 4.8.0 (14.07.2026), Vorgänger 4.7.1 / 4.7.2, Restore Point `DD_R480`, geplant 4.10 |
| Vault-Pfade DD | `kv/dd/db/meta`, `kv/dd/db/audit`, `kv/dd/s3/ingest`, `kv/dd/s3/read`, `kv/dd/s3/cleanup`, `kv/dd/tls/arch`, `kv/dd/oidc/gateway`, `kv/dd/ldap/read`, `kv/dd/archive/svc` |
| Technische Konten DD | `svc-dd-ingest`, `svc-dd-read`, `svc-dd-cleanup`; AD-Gruppen `BAVD-DD-*`, `dd-ops`, `DD_DBA` |
| Verträge | `WV-2023-0155` (ArchivLine-Wartung), `RV-2021-0338` (Oracle), **`LS-ZRB-2021-4408` (Leistungsschein ZRB, gilt für Mars und BUPP)** |
| Kennzahlen DD | Verfügbarkeit gemessen 99,71 %, Lesezugriff p95 780 ms, Bucket 64 TB brutto |
| Servicedesk (zentral) | 0800 1180 100 |
