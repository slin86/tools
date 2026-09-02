#!/usr/bin/env python3
"""
Uptime Kuma v1 JSON Export → v2 Import
Importiert Monitors, Notifications und Status Pages aus einem v1-Backup in v2.

Abhängigkeiten:
    pip install uptime-kuma-api

Verwendung:
    python kuma_import.py \
        --file backup.json \
        --url http://uptime-kuma-v2:3001 \
        --username admin \
        --password secret

    # Nur Monitors importieren:
    python kuma_import.py --file backup.json --url ... --skip-notifications --skip-status-pages

    # Dry-Run (kein tatsächlicher Import):
    python kuma_import.py --file backup.json --url ... --dry-run
"""

import argparse
import json
import sys
import time
from uptime_kuma_api import UptimeKumaApi, MonitorType


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_backup(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def map_monitor_type(v1_type: str) -> str:
    """
    Mappt v1-Typnamen auf v2-Typnamen.
    Die meisten sind identisch; hier nur bekannte Abweichungen.
    """
    mapping = {
        "http":         "http",
        "keyword":      "keyword",
        "json-query":   "json-query",
        "tcp":          "tcp",
        "ping":         "ping",
        "dns":          "dns",
        "push":         "push",
        "steam":        "steam",
        "mqtt":         "mqtt",
        "sqlserver":    "sqlserver",
        "postgres":     "postgres",
        "mysql":        "mysql",
        "mongodb":      "mongodb",
        "radius":       "radius",
        "redis":        "redis",
        "group":        "group",
    }
    return mapping.get(v1_type, v1_type)


def build_monitor_kwargs(m: dict) -> dict:
    """Extrahiert alle relevanten Felder aus einem v1-Monitor-Objekt."""
    kwargs = {
        "type":                 map_monitor_type(m.get("type", "http")),
        "name":                 m.get("name", "Unnamed"),
        "interval":             m.get("interval", 60),
        "retryInterval":        m.get("retryInterval", 60),
        "maxretries":           m.get("maxretries", 0),
        "upsideDown":           m.get("upsideDown", False),
        "notificationIDList":   [],   # wird nach Notification-Import befüllt
    }

    # Felder die nicht für alle Typen gelten – nur setzen wenn vorhanden
    optional_fields = [
        "url", "method", "hostname", "port", "keyword", "invertKeyword",
        "maxredirects", "accepted_statuscodes", "proxyId", "body", "headers",
        "authMethod", "basicauth-user", "basicauth-pass",
        "httpBodyEncoding", "jsonPath", "expectedValue",
        "dns_resolve_server", "dns_resolve_type",
        "mqttUsername", "mqttPassword", "mqttTopic", "mqttSuccessMessage",
        "databaseConnectionString", "databaseQuery",
        "radiusUsername", "radiusPassword", "radiusCalledStationId",
        "radiusCallingStationId", "radiusSecret",
        "resendInterval", "packetSize",
        "expiryNotification", "ignoreTls", "description",
    ]
    for field in optional_fields:
        if field in m and m[field] is not None:
            kwargs[field] = m[field]

    return kwargs


# ---------------------------------------------------------------------------
# Import-Funktionen
# ---------------------------------------------------------------------------

def import_notifications(api: UptimeKumaApi, notifications: list, dry_run: bool) -> dict:
    """
    Gibt ein Mapping zurück: alter Name → neue ID
    """
    name_to_new_id = {}
    print(f"\n📣 Notifications: {len(notifications)} gefunden")

    for n in notifications:
        name = n.get("name", "Unnamed")
        n_type = n.get("type", "")

        # Config ist in v1 ein dict, die API erwartet es als JSON-String
        config = n.copy()
        config.pop("id", None)
        config.pop("userId", None)
        config.pop("name", None)
        config.pop("type", None)
        config.pop("isDefault", None)
        config.pop("active", None)

        print(f"  → Notification: '{name}' (Typ: {n_type})")

        if not dry_run:
            try:
                result = api.add_notification(
                    name=name,
                    type=n_type,
                    isDefault=n.get("isDefault", False),
                    active=n.get("active", True),
                    **config,
                )
                new_id = result.get("id")
                name_to_new_id[name] = new_id
                print(f"     ✅ Erstellt mit ID {new_id}")
            except Exception as e:
                print(f"     ❌ Fehler: {e}")
        else:
            print(f"     [DRY-RUN] Würde erstellt werden")

    return name_to_new_id


def import_monitors(
    api: UptimeKumaApi,
    monitors: list,
    notification_name_to_id: dict,
    dry_run: bool,
) -> dict:
    """
    Importiert Monitors und gibt ein Mapping zurück: alter Name → neue ID.
    Gruppen werden zuerst importiert.
    """
    old_id_to_new_id = {}
    print(f"\n🖥️  Monitors: {len(monitors)} gefunden")

    # Gruppen zuerst sortieren
    groups   = [m for m in monitors if m.get("type") == "group"]
    others   = [m for m in monitors if m.get("type") != "group"]
    ordered  = groups + others

    # Alten Namen → alten ID für spätere parent-Zuordnung
    old_id_to_name = {m["id"]: m.get("name", "") for m in monitors if "id" in m}

    for m in ordered:
        kwargs = build_monitor_kwargs(m)
        name   = kwargs["name"]

        # Notifications verknüpfen
        old_notif_ids = m.get("notificationIDList", {})
        if isinstance(old_notif_ids, dict):
            old_notif_ids = list(old_notif_ids.keys())
        new_notif_ids = []
        for old_id in old_notif_ids:
            # v1 speichert Notification-IDs als Keys, suche den Namen
            for n in monitors:
                pass  # Notifications sind separat – wir nutzen name_to_id direkt
        # Alle bekannten Notification-IDs nach Namen mappen
        kwargs["notificationIDList"] = list(notification_name_to_id.values())

        # Parent-Gruppe zuordnen
        parent_old_id = m.get("parent")
        if parent_old_id is not None and parent_old_id in old_id_to_new_id:
            kwargs["parent"] = old_id_to_new_id[parent_old_id]

        monitor_type = kwargs.get("type", "?")
        print(f"  → Monitor: '{name}' (Typ: {monitor_type})")

        if not dry_run:
            try:
                result = api.add_monitor(**kwargs)
                new_id = result.get("monitorId")
                if "id" in m:
                    old_id_to_new_id[m["id"]] = new_id
                print(f"     ✅ Erstellt mit ID {new_id}")
                time.sleep(0.3)   # kurze Pause um den Server nicht zu überlasten
            except Exception as e:
                print(f"     ❌ Fehler bei '{name}': {e}")
        else:
            print(f"     [DRY-RUN] Würde erstellt werden")

    return old_id_to_new_id


def import_status_pages(
    api: UptimeKumaApi,
    status_pages: list,
    monitor_old_to_new_id: dict,
    dry_run: bool,
):
    print(f"\n📄 Status Pages: {len(status_pages)} gefunden")

    for sp in status_pages:
        title = sp.get("title", "Unnamed")
        slug  = sp.get("slug", title.lower().replace(" ", "-"))

        # publicGroupList: Monitor-IDs auf neue IDs umschreiben
        public_group_list = []
        for group in sp.get("publicGroupList", []):
            new_group = {
                "name":    group.get("name", ""),
                "weight":  group.get("weight", 1),
                "monitorList": [],
            }
            for mon in group.get("monitorList", []):
                old_id = mon.get("id")
                new_id = monitor_old_to_new_id.get(old_id)
                if new_id:
                    new_group["monitorList"].append({"id": new_id})
                else:
                    print(f"     ⚠️  Monitor ID {old_id} nicht gefunden, wird übersprungen")
            public_group_list.append(new_group)

        print(f"  → Status Page: '{title}' (Slug: {slug})")

        if not dry_run:
            try:
                api.add_status_page(slug=slug, title=title)
                api.save_status_page(
                    slug=slug,
                    title=title,
                    description=sp.get("description", ""),
                    theme=sp.get("theme", "light"),
                    published=sp.get("published", True),
                    showTags=sp.get("showTags", False),
                    domainNameList=sp.get("domainNameList", []),
                    customCSS=sp.get("customCSS", ""),
                    footerText=sp.get("footerText", ""),
                    showPoweredBy=sp.get("showPoweredBy", True),
                    publicGroupList=public_group_list,
                    imgDataUrl=sp.get("icon", ""),
                )
                print(f"     ✅ Erstellt")
            except Exception as e:
                print(f"     ❌ Fehler bei '{title}': {e}")
        else:
            print(f"     [DRY-RUN] Würde erstellt werden")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Importiert ein Uptime Kuma v1 JSON-Backup in eine v2-Instanz."
    )
    parser.add_argument("--file",     required=True,  help="Pfad zur v1 backup.json")
    parser.add_argument("--url",      required=True,  help="URL der v2-Instanz, z.B. http://localhost:3001")
    parser.add_argument("--username", required=True,  help="Admin-Benutzername")
    parser.add_argument("--password", required=True,  help="Admin-Passwort")
    parser.add_argument("--skip-notifications",  action="store_true", help="Notifications nicht importieren")
    parser.add_argument("--skip-monitors",       action="store_true", help="Monitors nicht importieren")
    parser.add_argument("--skip-status-pages",   action="store_true", help="Status Pages nicht importieren")
    parser.add_argument("--dry-run",             action="store_true", help="Nur anzeigen, nicht importieren")
    args = parser.parse_args()

    # Backup laden
    print(f"📂 Lade Backup: {args.file}")
    try:
        backup = load_backup(args.file)
    except FileNotFoundError:
        print(f"❌ Datei nicht gefunden: {args.file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Ungültiges JSON: {e}")
        sys.exit(1)

    monitors      = backup.get("monitorList",    [])
    notifications = backup.get("notificationList", [])
    status_pages  = backup.get("statusPageList", [])

    print(f"   Monitors:      {len(monitors)}")
    print(f"   Notifications: {len(notifications)}")
    print(f"   Status Pages:  {len(status_pages)}")

    if args.dry_run:
        print("\n⚠️  DRY-RUN Modus – es werden keine Daten verändert\n")

    # Verbinden
    print(f"\n🔌 Verbinde mit {args.url} ...")
    try:
        with UptimeKumaApi(args.url) as api:
            api.login(args.username, args.password)
            print("✅ Login erfolgreich\n")

            notification_name_to_id = {}
            monitor_old_to_new_id   = {}

            if not args.skip_notifications:
                notification_name_to_id = import_notifications(api, notifications, args.dry_run)

            if not args.skip_monitors:
                monitor_old_to_new_id = import_monitors(
                    api, monitors, notification_name_to_id, args.dry_run
                )

            if not args.skip_status_pages:
                import_status_pages(api, status_pages, monitor_old_to_new_id, args.dry_run)

    except Exception as e:
        print(f"\n❌ Verbindungsfehler: {e}")
        sys.exit(1)

    print("\n🎉 Import abgeschlossen!")


if __name__ == "__main__":
    main()