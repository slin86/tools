#!/usr/bin/env python3
"""
Importiert Secrets aus der bereinigten JSON-Datei in den neuen Test-Key-Vault.

Workflow:
  1. secrets_export.json aus dem Export-Script liegt vor
  2. Du hast die Datei manuell bereinigt (unnötige/Prod-only Secrets entfernt,
     Werte für Test-Umgebung angepasst)
  3. Dieses Script liest die bereinigte Datei und schreibt die Secrets in den
     neuen Test-Key-Vault

Prerequisites:
    pip install azure-identity azure-keyvault-secrets

Authentication:
    Wie im Export-Script — DefaultAzureCredential
"""

import json
import logging
import sys
import time
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from azure.core.exceptions import HttpResponseError

# ---------------------------------------------------------------------------
# Konfiguration — bitte anpassen
# ---------------------------------------------------------------------------
TEST_VAULT_URL = "https://geofox-kv-prod.vault.azure.net"

# Bereinigte Export-Datei (nach manueller Review)
INPUT_FILE = Path("secrets_export_prod.json")

# Vorhandene Secrets im Ziel-Vault überschreiben?
OVERWRITE_EXISTING = False

# Pause zwischen API-Calls (Sekunden) — verhindert Throttling
DELAY_SECONDS = 0.3
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def import_secrets(vault_url: str, input_file: Path, overwrite: bool) -> None:
    if not input_file.exists():
        log.error("Eingabedatei nicht gefunden: %s", input_file)
        sys.exit(1)

    data = json.loads(input_file.read_text())
    secrets: dict = data.get("secrets", {})

    if not secrets:
        log.error("Keine Secrets in der Datei gefunden. Abbruch.")
        sys.exit(1)

    summary = data.get("_summary", {})
    log.info(
        "Lade %d Secrets aus '%s' (Quelle: %s, exportiert: %s)",
        len(secrets),
        input_file,
        summary.get("source_vault", "unbekannt"),
        summary.get("exported_at", "unbekannt"),
    )

    log.info("Verbinde mit Test Key Vault: %s", vault_url)
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)

    # Bereits vorhandene Secrets im Ziel einlesen (für Overwrite-Check)
    existing_names: set[str] = set()
    if not overwrite:
        log.info("Lese vorhandene Secrets im Ziel-Vault...")
        existing_names = {
            p.name for p in client.list_properties_of_secrets()
        }
        log.info("  Vorhandene Secrets: %d", len(existing_names))

    results = {"created": [], "skipped": [], "failed": []}

    for name, meta in secrets.items():
        # Interne Metadaten-Keys überspringen
        if name.startswith("_"):
            continue

        if name in existing_names:
            log.warning("  SKIP (bereits vorhanden, OVERWRITE_EXISTING=False): %s", name)
            results["skipped"].append(name)
            continue

        value = meta.get("value")
        if value is None:
            log.warning("  SKIP (kein Wert): %s", name)
            results["skipped"].append(name)
            continue

        try:
            client.set_secret(
                name=name,
                value=value,
                content_type=meta.get("content_type"),
                tags=meta.get("tags") or {},
            )
            log.info("  OK: %s", name)
            results["created"].append(name)
        except HttpResponseError as exc:
            log.error("  FEHLER bei '%s': %s", name, exc.message)
            results["failed"].append(name)
        except Exception as exc:  # noqa: BLE001
            log.error("  UNERWARTETER FEHLER bei '%s': %s", name, exc)
            results["failed"].append(name)

        time.sleep(DELAY_SECONDS)

    # Abschlussbericht
    log.info(
        "\n=== Import abgeschlossen ===\n"
        "  Erstellt:     %d\n"
        "  Übersprungen: %d\n"
        "  Fehlgeschlag: %d",
        len(results["created"]),
        len(results["skipped"]),
        len(results["failed"]),
    )

    if results["failed"]:
        log.error("Fehlgeschlagene Secrets: %s", results["failed"])
        sys.exit(1)


if __name__ == "__main__":
    if "<TEST-KEYVAULT-NAME>" in TEST_VAULT_URL:
        log.error("Bitte TEST_VAULT_URL in der Konfiguration anpassen!")
        sys.exit(1)

    import_secrets(TEST_VAULT_URL, INPUT_FILE, OVERWRITE_EXISTING)