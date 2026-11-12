# Deployment: Chat und Ingest

Manifeste für zwei Dienste im selben Namespace. Der docling-graph-service hat ein eigenes Manifest in seinem
Repo (`docling-graph/deploy/k8s`). Offene Fragen: [`../../docs/OFFENE-PUNKTE.md`](../../docs/OFFENE-PUNKTE.md).

| Datei | Inhalt |
|---|---|
| `config.yaml` | ConfigMaps `chat-config`, `ingest-config` (Einstellungen ohne Geheimnisse) |
| `chat.yaml` | Deployment + Service `chat` (Port 8501) |
| `ingest.yaml` | Deployment + Service `ingest` (Port 8090) |
| `secrets.example.yaml` | Vorlage für `chat-secrets`, `ingest-secrets` |
| `networkpolicy.yaml` | Zugriffsregeln; noch nicht aktiv (Labels bestätigen) |
| `examples/virtualservice.example.yaml` | Beispiel für den Zugang zur Ingest-API über das Gateway |

## Wer spricht mit wem

| Von | Nach | Port |
|---|---|---|
| Anmelde-Proxy (PAG) | `chat` | 8501 |
| Gateway | `ingest` | 8090 |
| `ingest` | `dgs` (docling-graph-service) | 8080 |
| `chat`, `ingest` | OpenSearch (extern) | laut URL |
| `chat` | Sprachmodell, Embeddings (extern) | laut URL |

## Schritte

1. **Images bauen und in die Registry schieben** (Build-Kontext ist die Wurzel des Repos):
   ```bash
   docker build -t REGISTRY/bhb/chat-system:0.1.0    -f chat-system/Dockerfile .
   docker build -t REGISTRY/bhb/ingest-service:0.1.0 -f ingest/Dockerfile .
   ```
   Registry und Tag in `kustomization.yaml` eintragen.
2. **Werte je Umgebung** in `config.yaml` setzen (alle Platzhalter in GROSSBUCHSTABEN).
3. **Secrets anlegen:**
   ```bash
   oc create secret generic chat-secrets \
     --from-literal=RAG__OPENSEARCH__PASSWORD=… --from-literal=RAG__EMBEDDING__API_KEY=… --from-literal=RAG__LLM__API_KEY=…
   oc create secret generic ingest-secrets \
     --from-literal=INGEST__API_KEY=… --from-literal=OSI__OPENSEARCH__PASSWORD=…
   ```
4. **Ontologie als ConfigMap:**
   ```bash
   oc create configmap bhb-ontology --from-file=ontology.yaml=user-manual-books/handbuch_daten/Ontologie/ontology.yaml
   ```
5. **Anwenden und prüfen:**
   ```bash
   oc apply -k deploy/k8s
   oc get pods
   oc exec deploy/chat -- chat-doctor
   oc port-forward svc/ingest 8090:8090 &
   curl -H "X-API-Key: …" http://localhost:8090/v1/info
   ```

## Wichtig

- **Ressourcen:** Chat 250m CPU / 512Mi angefordert (Limit 1 CPU / 1Gi), Ingest 100m / 256Mi (Limit 500m / 768Mi).
- **Nichts wird gespeichert.** Die Gespräche liegen im Pod (emptyDir) und sind nach jedem Neustart weg.
- **Ein Replikat je Dienst**, Strategie `Recreate`.
- **Benutzer-ID:** die Pods laufen unter der ID, die OpenShift vergibt, mit schreibgeschütztem Dateisystem.
- **Zertifikat von OpenSearch:** bei eigener CA die ConfigMap `opensearch-ca` anlegen
  (`oc create configmap opensearch-ca --from-file=ca.crt=…`), die auskommentierten Zeilen in `chat.yaml` und
  `ingest.yaml` aktivieren und `RAG__OPENSEARCH__CA_CERTS` bzw. `OSI__OPENSEARCH__CA_CERTS` auf `/ca/ca.crt` setzen.
- **Chat nur über den Anmelde-Proxy.** Kein eigener Zugang am Proxy vorbei, sonst kann jemand die Header fälschen.
- **Ingest-API:** ein Aufruf dauert Minuten. Die Zeitgrenze am Gateway muss das erlauben (Beispiel: 3600 s).
