"""Automatisch erzeugt aus ontology.yaml — nicht von Hand ändern."""
from __future__ import annotations

from datetime import date as _date
from enum import Enum
from typing import Annotated, List, Literal, Optional, Union

from pydantic import BaseModel, Field, StringConstraints


# --- Basistypen mit Muster aus datatypes ---
Hostname = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{1,30}(\.[a-z0-9-]+)*$")]
IPv4 = Annotated[str, StringConstraints(pattern=r"^(\d{1,3}\.){3}\d{1,3}$")]
CIDR = Annotated[str, StringConstraints(pattern=r"^(\d{1,3}\.){3}\d{1,3}/\d{1,2}$")]
Port = Annotated[int, Field(ge=1, le=65535)]
PhoneExt = Annotated[str, StringConstraints(pattern=r"^\d{3,4}$")]
DocId = Annotated[str, StringConstraints(pattern=r"^BHB-(PLT|VRF)-\d{4}$")]
CiId = Annotated[str, StringConstraints(pattern=r"^CI-(PLT|VRF)-\d{4}$")]
TicketId = Annotated[str, StringConstraints(pattern=r"^(ESSUP|DDSUP|VPPSUP|CAASUP|ZSDSUP)-\d{3,4}$")]
SopId = Annotated[str, StringConstraints(pattern=r"^SOP-(\d+|(CAAS|ZSD|DD|VPP)-\d{2})$")]
FwId = Annotated[str, StringConstraints(pattern=r"^FW-(ES|DD|VPP|CAAS|ZSD)-\d{3}$")]
OpenItemId = Annotated[str, StringConstraints(pattern=r"^OP(-(CAAS|ZSD))?-\d{2}$")]
ZoneId = Annotated[str, StringConstraints(pattern=r"^ZONE-[A-Z]+(-[A-Z]{2})?$")]
ContractId = Annotated[str, StringConstraints(pattern=r"^((RV|WV)-\d{4}-\d{4}|LS-ZRB-\d{4}-\d{4})$")]
VaultPath = Annotated[str, StringConstraints(pattern=r"^kv/[a-z0-9/_<>*-]+$")]
K8sName = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")]


class Polarity(str, Enum):
    positive = "positive"
    negative = "negative"


class SystemKind(str, Enum):
    fachverfahren = "fachverfahren"
    plattformdienst = "plattformdienst"
    basisdienst = "basisdienst"
    fremdsystem = "fremdsystem"


class ComponentKind(str, Enum):
    webtier = "webtier"
    apptier = "apptier"
    worker = "worker"
    broker = "broker"
    gateway = "gateway"
    datenbank = "datenbank"
    adapter = "adapter"
    batch = "batch"
    monitoring = "monitoring"
    sonstige = "sonstige"


class DeploymentModel(str, Enum):
    container = "container"
    virtuelle_maschine = "virtuelle_maschine"
    appliance = "appliance"
    extern_betrieben = "extern_betrieben"


class EnvironmentKind(str, Enum):
    entwicklung = "entwicklung"
    test = "test"
    abnahme = "abnahme"
    produktion = "produktion"
    vorabpruefung = "vorabpruefung"


class DependencyKind(str, Enum):
    identitaet = "identitaet"
    zertifikat = "zertifikat"
    geheimnis = "geheimnis"
    netz = "netz"
    speicher = "speicher"
    plattform = "plattform"
    messaging = "messaging"
    datenbank = "datenbank"
    monitoring = "monitoring"
    dienstleister = "dienstleister"


class Criticality(str, Enum):
    kritisch = "kritisch"
    hoch = "hoch"
    mittel = "mittel"
    niedrig = "niedrig"


class ImpactSeverity(str, Enum):
    keine = "keine"
    eingeschraenkt = "eingeschraenkt"
    ausfall = "ausfall"
    unbekannt = "unbekannt"


class IncidentSeverity(str, Enum):
    sev1 = "sev1"
    sev2 = "sev2"
    sev3 = "sev3"


class CertRenewalMode(str, Enum):
    automatisch_acme = "automatisch_acme"
    gemischt = "gemischt"
    manuell = "manuell"


class ProtectionLevel(str, Enum):
    normal = "normal"
    hoch = "hoch"
    sehr_hoch = "sehr_hoch"


class ServiceClass(str, Enum):
    bronze = "bronze"
    silber = "silber"
    gold = "gold"


class Protocol(str, Enum):
    tcp = "tcp"
    udp = "udp"
    https = "https"
    http = "http"
    ldaps = "ldaps"
    amqp = "amqp"
    kafka = "kafka"
    jdbc = "jdbc"
    s3 = "s3"
    nfs = "nfs"
    ssh = "ssh"


class OrgUnitKind(str, Enum):
    behoerde = "behoerde"
    bereich = "bereich"
    team = "team"
    dienstleister = "dienstleister"
    rechenzentrum = "rechenzentrum"


class ProcedureTrigger(str, Enum):
    geplant = "geplant"
    anlassbezogen = "anlassbezogen"
    notfall = "notfall"
    wiederkehrend = "wiederkehrend"


class EventDirection(str, Enum):
    eingehend = "eingehend"
    ausgehend = "ausgehend"
    bidirektional = "bidirektional"


class Provenance(BaseModel):
    """Woher der Wert stammt. Pflicht für jede Extraktion, Grundlage der Zitierbarkeit."""
    document_id: DocId = Field(..., description="Dokument, aus dem die Aussage stammt")
    chapter: Optional[str] = Field(None, description="Kapitelnummer, z. B. 5.3")
    page: Optional[int] = Field(None, description="Seitenzahl im PDF")
    table_ref: Optional[str] = Field(None, description="Tabellennummer, z. B. Tabelle 12")
    figure_ref: Optional[str] = Field(None, description="Abbildungsnummer, z. B. Abbildung 3")
    quote: Optional[str] = Field(None, description="Wörtlicher Satz als Belegstelle, max. 300 Zeichen")
    confidence: Optional[float] = Field(None, description="0.0–1.0, Vertrauen des Extraktors")


class NodeBase(BaseModel):
    """Gemeinsame Felder aller Knoten."""
    id: str = Field(..., description="Stabile ID, aus identity gebildet: <class>:<key>, kleingeschrieben")
    label: str = Field(..., description="Anzeigename wie im Dokument geschrieben")
    aliases: List[str] = Field(default_factory=list, description="Weitere Schreibweisen und Abkürzungen desselben Knotens")
    description: Optional[str] = Field(None, description="Ein bis zwei Sätze aus dem Dokument")
    provenance: List[Provenance] = Field(default_factory=list, description="Alle Stellen, an denen der Knoten belegt ist")


class EdgeBase(BaseModel):
    """Gemeinsame Felder aller Kanten."""
    type: str = Field(..., description="Relationsname aus relations[]")
    source_id: str = Field(...)
    target_id: str = Field(...)
    polarity: Polarity = Field(..., description="negative = die Beziehung wird im Text ausdrücklich verneint")
    qualifier: Optional[str] = Field(None, description="Einschränkung im Text ('nur für neue Sitzungen', 'nur das Ops-Cockpit')")
    provenance: List[Provenance] = Field(default_factory=list)


class Document(NodeBase):
    """Betriebshandbuch"""
    node_type: Literal["Document"] = "Document"
    doc_id: DocId = Field(...)
    title: str = Field(...)
    version: Optional[str] = Field(None)
    valid_from: Optional[_date] = Field(None, description="Feld 'Stand' auf der Titelseite")
    classification: Optional[str] = Field(None)
    ci_id: Optional[CiId] = Field(None)


class OrgUnit(NodeBase):
    """Organisationseinheit"""
    node_type: Literal["OrgUnit"] = "OrgUnit"
    kind: OrgUnitKind = Field(...)
    short_name: Optional[str] = Field(None)
    mailbox: Optional[str] = Field(None)
    chat_channel: Optional[str] = Field(None)
    jira_project: Optional[str] = Field(None)


class Person(NodeBase):
    """Person"""
    node_type: Literal["Person"] = "Person"
    role_title: Optional[str] = Field(None)
    phone_ext: Optional[PhoneExt] = Field(None)
    email: Optional[str] = Field(None)
    org_unit: Optional[str] = Field(None, description="OrgUnit, dem die Person zugeordnet ist")


class Contract(NodeBase):
    """Vertrag oder Leistungsschein"""
    node_type: Literal["Contract"] = "Contract"
    contract_id: ContractId = Field(...)
    subject: Optional[str] = Field(None, description="Leistungsgegenstand")
    valid_until: Optional[_date] = Field(None)
    service_class: Optional[ServiceClass] = Field(None)


class System(NodeBase):
    """Das oberste betriebliche Objekt. Jedes Betriebshandbuch beschreibt genau ein System."""
    node_type: Literal["System"] = "System"
    kind: SystemKind = Field(...)
    ci_id: Optional[CiId] = Field(None)
    purpose: Optional[str] = Field(None, description="Fachlicher Auftrag in einem Satz")
    deployment_model: Optional[DeploymentModel] = Field(None)
    protection_level: Optional[ProtectionLevel] = Field(None, description="Schutzbedarf nach Verfügbarkeit")
    availability_target: Optional[float] = Field(None)
    rto: Optional[str] = Field(None)
    rpo: Optional[str] = Field(None)
    service_hours: Optional[str] = Field(None)
    cert_renewal_mode: Optional[CertRenewalMode] = Field(None, description="Ein Unterscheidungsmerkmal des Korpus")


class Component(NodeBase):
    """Technischer Baustein innerhalb eines Systems (Pod, Deployment, Prozess, Adapter)."""
    node_type: Literal["Component"] = "Component"
    kind: ComponentKind = Field(...)
    replicas: Optional[int] = Field(None)
    technology: Optional[str] = Field(None)
    quota: Optional[str] = Field(None)
    restart_note: Optional[str] = Field(None, description="Was beim Neustart zu beachten ist (PodDisruptionBudget")


class Host(NodeBase):
    """Server oder Knoten"""
    node_type: Literal["Host"] = "Host"
    hostname: Hostname = Field(...)
    ip: Optional[IPv4] = Field(None)
    role: Optional[str] = Field(None)
    os: Optional[str] = Field(None)
    fire_section: Optional[str] = Field(None, description="Brandabschnitt")


class Environment(NodeBase):
    """Umgebung oder Cluster"""
    node_type: Literal["Environment"] = "Environment"
    kind: EnvironmentKind = Field(...)
    api_endpoint: Optional[str] = Field(None)
    worker_nodes: Optional[int] = Field(None)
    app_domain: Optional[str] = Field(None)


class Namespace(NodeBase):
    """Namespace"""
    node_type: Literal["Namespace"] = "Namespace"
    label: K8sName = Field(...)
    quota: Optional[str] = Field(None)


class NetworkZone(NodeBase):
    """Netzzone"""
    node_type: Literal["NetworkZone"] = "NetworkZone"
    zone_id: ZoneId = Field(...)
    cidr: Optional[CIDR] = Field(None)
    site: Optional[str] = Field(None)


class FirewallRule(NodeBase):
    """Zeile der Portmatrix. Trägt die Netzkanten des Graphen."""
    node_type: Literal["FirewallRule"] = "FirewallRule"
    fw_id: FwId = Field(...)
    source_desc: str = Field(..., description="Quelle wie im Dokument benannt")
    target_desc: str = Field(..., description="Ziel wie im Dokument benannt")
    port: Optional[Port] = Field(None)
    protocol: Optional[Protocol] = Field(None)
    purpose: Optional[str] = Field(None)


class DataStore(NodeBase):
    """Datenbank, Topic, Objektspeicher, Volume, Archiv."""
    node_type: Literal["DataStore"] = "DataStore"
    technology: Optional[str] = Field(None)
    capacity: Optional[str] = Field(None)
    retention: Optional[str] = Field(None)
    backup_note: Optional[str] = Field(None)


class EventChannel(NodeBase):
    """Broker, Trigger oder Topic, über den Systeme Ereignisse austauschen."""
    node_type: Literal["EventChannel"] = "EventChannel"
    channel_kind: Optional[str] = Field(None)
    event_type: Optional[str] = Field(None)
    direction: Optional[EventDirection] = Field(None)
    guarantee: Optional[str] = Field(None, description="Zustellgarantie, Wiederholungen, Backoff")


class IdentityClient(NodeBase):
    """OIDC-Client, über den ein System die zentrale Anmeldung nutzt."""
    node_type: Literal["IdentityClient"] = "IdentityClient"
    realm: Optional[str] = Field(None)
    flow: Optional[str] = Field(None)
    secret_rotation: Optional[str] = Field(None, description="Rotationsregel und Abstimmungspflicht")


class Certificate(NodeBase):
    """Zertifikat"""
    node_type: Literal["Certificate"] = "Certificate"
    subject: Optional[str] = Field(None)
    keystore_path: Optional[str] = Field(None)
    renewal_mode: CertRenewalMode = Field(...)
    valid_until: Optional[_date] = Field(None)
    lifetime_days: Optional[int] = Field(None)
    alert_thresholds: Optional[str] = Field(None)


class CertificateAuthority(NodeBase):
    """Zertifizierungsstelle"""
    node_type: Literal["CertificateAuthority"] = "CertificateAuthority"
    ca_role: Optional[str] = Field(None)
    valid_period: Optional[str] = Field(None)
    profile: Optional[str] = Field(None)


class SecretStorePath(NodeBase):
    """Pfad im zentralen Secret-Management, über den ein System Zugangsdaten bezieht."""
    node_type: Literal["SecretStorePath"] = "SecretStorePath"
    vault_path: VaultPath = Field(...)
    content_desc: Optional[str] = Field(None)


class Procedure(NodeBase):
    """Arbeitsanweisung (SOP)"""
    node_type: Literal["Procedure"] = "Procedure"
    sop_id: SopId = Field(...)
    title: str = Field(...)
    trigger: Optional[ProcedureTrigger] = Field(None)
    lead_time: Optional[str] = Field(None, description="Vorlauf für die Abstimmung")
    steps: List[str] = Field(default_factory=list, description="Schritte in Reihenfolge, je Schritt ein Eintrag")
    commands: List[str] = Field(default_factory=list, description="Wörtliche Befehle aus den Codeblöcken")
    rollback: Optional[str] = Field(None, description="Rückfallweg, falls beschrieben")


class MaintenanceWindow(NodeBase):
    """Wartungsfenster"""
    node_type: Literal["MaintenanceWindow"] = "MaintenanceWindow"
    schedule: str = Field(...)
    notice_period: Optional[str] = Field(None)


class StartupStep(NodeBase):
    """Ein Schritt der Wiederanlaufreihenfolge des Gesamtverbunds (SOP-CAAS-06)."""
    node_type: Literal["StartupStep"] = "StartupStep"
    order: int = Field(...)
    duration: Optional[str] = Field(None)
    precondition: Optional[str] = Field(None)


class Incident(NodeBase):
    """Störung / Vorgang"""
    node_type: Literal["Incident"] = "Incident"
    ticket_id: TicketId = Field(...)
    title: str = Field(...)
    date: Optional[_date] = Field(None)
    severity: Optional[IncidentSeverity] = Field(None)
    duration: Optional[str] = Field(None)
    root_cause: Optional[str] = Field(None)
    resolution: Optional[str] = Field(None)
    process_change: Optional[str] = Field(None, description="Was danach verbindlich geändert wurde")


class FailureMode(NodeBase):
    """Wiederkehrendes Fehlerbild mit Symptom, Prüfung und Lösung."""
    node_type: Literal["FailureMode"] = "FailureMode"
    symptom: str = Field(...)
    log_evidence: Optional[str] = Field(None, description="Charakteristische Logzeile oder Exception")
    check: Optional[str] = Field(None)
    remedy: Optional[str] = Field(None)


class ImpactStatement(NodeBase):
    """Reifizierte Aussage 'Ereignis X an Dienst A wirkt bei Konsument B so'. Zieht die Auswirkungsmatrizen (BHB-PLT-0001 Tab. 12, BHB-PLT-0007 Tab. 8) in den Graphen. Kern für Fragen der Form 'Ich starte X neu — wen trifft es?'."""
    node_type: Literal["ImpactStatement"] = "ImpactStatement"
    event: str = Field(..., description="Auslösendes Ereignis, z. B. 'Vault versiegelt', 'Knoten entleeren'")
    causing_system: Optional[str] = Field(None, description="System, an dem das Ereignis stattfindet")
    affected_system: str = Field(...)
    severity: ImpactSeverity = Field(...)
    symptom: Optional[str] = Field(None, description="Wortlaut der Zelle")
    mitigation: Optional[str] = Field(None, description="Überbrückung, falls genannt")


class Alert(NodeBase):
    """Alarm"""
    node_type: Literal["Alert"] = "Alert"
    expression: Optional[str] = Field(None)
    threshold: Optional[str] = Field(None)
    reaction: Optional[str] = Field(None, description="Welche SOP oder welcher Weg folgt")


class OpenItem(NodeBase):
    """Offener Punkt"""
    node_type: Literal["OpenItem"] = "OpenItem"
    openitem_id: OpenItemId = Field(...)
    subject: str = Field(...)
    due: Optional[_date] = Field(None)
    owner: Optional[str] = Field(None, description="Person")


class Term(NodeBase):
    """Glossarbegriff"""
    node_type: Literal["Term"] = "Term"
    definition: str = Field(...)
    maps_to: Optional[str] = Field(None, description="Knoten, den der Begriff benennt")


class RelationType(str, Enum):
    DOCUMENTS = "DOCUMENTS"
    MENTIONED_IN = "MENTIONED_IN"
    RELATED_DOCUMENT = "RELATED_DOCUMENT"
    OPERATED_BY = "OPERATED_BY"
    RESPONSIBLE_FOR = "RESPONSIBLE_FOR"
    ESCALATES_TO = "ESCALATES_TO"
    CONTRACT_COVERS = "CONTRACT_COVERS"
    HAS_COMPONENT = "HAS_COMPONENT"
    RUNS_ON = "RUNS_ON"
    LOCATED_IN = "LOCATED_IN"
    TENANT_OF = "TENANT_OF"
    USES_DATASTORE = "USES_DATASTORE"
    ALLOWS_TRAFFIC = "ALLOWS_TRAFFIC"
    PUBLISHES_EVENT = "PUBLISHES_EVENT"
    CONSUMES_EVENT = "CONSUMES_EVENT"
    DEPENDS_ON = "DEPENDS_ON"
    AUTHENTICATES_VIA = "AUTHENTICATES_VIA"
    SECURED_BY = "SECURED_BY"
    ISSUED_BY = "ISSUED_BY"
    READS_SECRET = "READS_SECRET"
    GOVERNED_BY = "GOVERNED_BY"
    HAS_MAINTENANCE_WINDOW = "HAS_MAINTENANCE_WINDOW"
    PRECEDES = "PRECEDES"
    STEP_RESPONSIBILITY = "STEP_RESPONSIBILITY"
    AFFECTS = "AFFECTS"
    PARTNER_TICKET = "PARTNER_TICKET"
    INSTANCE_OF_FAILURE = "INSTANCE_OF_FAILURE"
    RESULTED_IN_CHANGE = "RESULTED_IN_CHANGE"
    DETECTED_BY = "DETECTED_BY"
    MONITORS = "MONITORS"
    IMPACT_OF = "IMPACT_OF"
    DEFINES_TERM = "DEFINES_TERM"


class Edge(EdgeBase):
    """Kante des Graphen; type ist auf die Relationsliste beschränkt."""
    type: RelationType = Field(..., description='Relationsname')


AnyNode = Annotated[Union[Document, OrgUnit, Person, Contract, System, Component, Host, Environment, Namespace, NetworkZone, FirewallRule, DataStore, EventChannel, IdentityClient, Certificate, CertificateAuthority, SecretStorePath, Procedure, MaintenanceWindow, StartupStep, Incident, FailureMode, ImpactStatement, Alert, OpenItem, Term], Field(discriminator="node_type")]


class GraphDocument(BaseModel):
    """Extraktionsergebnis für ein Betriebshandbuch."""
    document_id: str = Field(..., description='BHB-Kennung')
    nodes: List[AnyNode] = Field(default_factory=list)
    edges: List[Edge] = Field(default_factory=list)