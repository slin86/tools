#!/usr/bin/env python3
"""
Export all secrets from the legacy Azure Key Vault to a local JSON file.

Prerequisites:
    pip install azure-identity azure-keyvault-secrets

Authentication:
    Uses DefaultAzureCredential — funktioniert mit:
      - az login (lokal)
      - Managed Identity (CI/CD)
      - Environment Variables (AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID)
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# ---------------------------------------------------------------------------
# Konfiguration — bitte anpassen
# ---------------------------------------------------------------------------
LEGACY_VAULT_URL = "https://geofox-key-vault.vault.azure.net"

# Ausgabedatei (liegt lokal, NICHT ins Repo committen!)
OUTPUT_FILE = Path("secrets_export.json")
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


def export_secrets(vault_url: str, output_file: Path) -> None:
    log.info("Verbinde mit Legacy Key Vault: %s", vault_url)
    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=vault_url, credential=credential)

    secrets: dict[str, dict] = {}
    skipped: list[str] = []

    # Alle Secret-Namen listen (nur aktive, nicht disabled)
    secret_properties = list(client.list_properties_of_secrets())
    log.info("Gefundene Secrets: %d", len(secret_properties))

    for prop in secret_properties:
        name = prop.name

        # Deaktivierte Secrets überspringen
        if not prop.enabled:
            log.warning("  SKIP (disabled): %s", name)
            skipped.append(name)
            continue

        try:
            secret = client.get_secret(name)
            secrets[name] = {
                "value": secret.value,
                "content_type": prop.content_type,
                "tags": dict(prop.tags) if prop.tags else {},
                # Metadaten für Nachvollziehbarkeit
                "_export_meta": {
                    "source_vault": vault_url,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "version": secret.properties.version,
                },
            }
            log.info("  OK: %s", name)
        except Exception as exc:  # noqa: BLE001
            log.error("  FEHLER bei '%s': %s", name, exc)
            skipped.append(name)

    # Export-Zusammenfassung
    export_data = {
        "_summary": {
            "source_vault": vault_url,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "total_exported": len(secrets),
            "total_skipped": len(skipped),
            "skipped_names": skipped,
        },
        "secrets": secrets,
    }

    output_file.write_text(json.dumps(export_data, indent=2, ensure_ascii=False))
    log.info(
        "Export abgeschlossen: %d Secrets → %s  (übersprungen: %d)",
        len(secrets),
        output_file,
        len(skipped),
    )

    if skipped:
        log.warning("Übersprungene Secrets: %s", skipped)


if __name__ == "__main__":
    if "<LEGACY-KEYVAULT-NAME>" in LEGACY_VAULT_URL:
        log.error("Bitte LEGACY_VAULT_URL in der Konfiguration anpassen!")
        sys.exit(1)

    export_secrets(LEGACY_VAULT_URL, OUTPUT_FILE)