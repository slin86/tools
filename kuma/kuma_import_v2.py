#!/usr/bin/env python3
"""
Uptime Kuma v1 JSON Export → v2 Import
Importiert Monitors, Notifications und Status Pages aus einem v1-Backup in v2.

Abhängigkeiten:
    pip install uptime-kuma-api-v2

Verwendung:
    python kuma_import.py \
        --file backup.json \
        --url http://localhost:3001 \
        --username admin \
        --password secret

    # Dry-Run (kein tatsächlicher Import):
    python kuma_import.py --file backup.json --url ... --dry-run

    # Nur Monitors importieren:
    python kuma_import.py --file backup.json --url ... --skip-notifications --skip-status-pages
"""

import argparse
import json
import sys
import time

from uptime_kuma_api import UptimeKumaApi


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def load_backup(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_monitor_kwargs(m: dict) -> dict:
    """Extrahiert alle relevanten Felder aus einem v1-Monitor-Objekt.
    Typen werden als rohe Strings übergeben – keine Enum-Konvertierung nötig.
    """
    kwargs = {
        "type":          m.get("type", "http"),   # String direkt, kein Enum
        "name":          m.get("name", "Unnamed"),
        "interval":      max(m.get("interval", 60), 20),
        "retryInterval": max(m.get("retryInterval", 60), 20),
        "maxretries":    m.get("maxretries", 0),
        "upsideDown":    m.get("upsideDown", False),
    }

    optional_fields = [
        "url", "method", "hostname", "port", "keyword", "invertKeyword",
        "maxredirects", "accepted_statuscodes", "body", "headers",
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
        val = m.get(field)
        if val is not None:
            kwargs[field] = val

    return kwargs


# ---------------------------------------------------------------------------
# Import-Funktionen
# ---------------------------------------------------------------------------

def import_notifications(api: UptimeKumaApi, notifications: list, dry_run: bool) -> dict:
    """Gibt ein Mapping zurück: alter Name → neue ID"""
    name_to_new_id = {}
    print(f"\n📣 Notifications: {len(notifications)} gefunden")

    for n in notifications:
        name = n.get("name", "Unnamed")

        # v1 speichert alle Notification-Parameter als JSON-String in "config"
        raw_config = n.get("config", "{}")
        if isinstance(raw_config, str):
            try:
                config = json.loads(raw_config)
            except json.JSONDecodeError:
                config = {}
        else:
            config = raw_config or {}

        n_type = config.pop("type", n.get("type", ""))

        # Felder die die API selbst verwaltet entfernen
        for key in ("id", "userId", "name", "isDefault", "active"):
            config.pop(key, None)

        print(f"  → Notification: '{name}' (Typ: {n_type})")

        if not dry_run:
            try:
                result = api.add_notification(
                    name=name,
                    type=n_type,
                    isDefault=n.get("isDefault", False),
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


def topological_sort(monitors: list) -> list:
    """
    Sortiert Monitors so, dass jeder Parent vor seinen Kindern kommt.
    Funktioniert auch bei verschachtelten Gruppen.
    """
    by_id = {m["id"]: m for m in monitors if "id" in m}
    result = []
    visited = set()

    def visit(m):
        mid = m.get("id")
        if mid in visited:
            return
        visited.add(mid)
        # Erst den Parent importieren
        parent_id = m.get("parent")
        if parent_id is not None and parent_id in by_id:
            visit(by_id[parent_id])
        result.append(m)

    for m in monitors:
        visit(m)

    # Monitors ohne ID (sollte nicht vorkommen) ans Ende
    without_id = [m for m in monitors if "id" not in m]
    return result + without_id


def import_monitors(
    api: UptimeKumaApi,
    monitors: list,
    notification_name_to_id: dict,
    dry_run: bool,
) -> dict:
    """Importiert Monitors in topologischer Reihenfolge (Parents vor Kindern).
    Gibt Mapping zurück: alte ID → neue ID"""
    old_id_to_new_id = {}
    print(f"\n🖥️  Monitors: {len(monitors)} gefunden")

    ordered = topological_sort(monitors)

    all_notification_ids = list(notification_name_to_id.values())

    for m in ordered:
        kwargs = build_monitor_kwargs(m)
        name   = kwargs["name"]

        if all_notification_ids:
            kwargs["notificationIDList"] = all_notification_ids

        # Parent-Gruppe zuordnen
        parent_old_id = m.get("parent")
        if parent_old_id is not None:
            if parent_old_id in old_id_to_new_id:
                kwargs["parent"] = old_id_to_new_id[parent_old_id]
            elif dry_run:
                print(f"     [DRY-RUN] Parent-ID {parent_old_id} wird im echten Lauf gemappt")
            else:
                print(f"     ⚠️  Parent-ID {parent_old_id} nicht gemappt, wird ignoriert")

        print(f"  → Monitor: '{name}' (Typ: {m.get('type', '?')})")

        if not dry_run:
            try:
                result = api.add_monitor(**kwargs)
                new_id = result.get("monitorId")
                if "id" in m:
                    old_id_to_new_id[m["id"]] = new_id
                print(f"     ✅ Erstellt mit ID {new_id}")
                time.sleep(0.3)
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

        public_group_list = []
        for group in sp.get("publicGroupList", []):
            new_group = {
                "name":        group.get("name", ""),
                "weight":      group.get("weight", 1),
                "monitorList": [],
            }
            for mon in group.get("monitorList", []):
                old_id = mon.get("id")
                new_id = monitor_old_to_new_id.get(old_id)
                if new_id:
                    new_group["monitorList"].append({"id": new_id})
                else:
                    print(f"     ⚠️  Monitor-ID {old_id} nicht gemappt, wird übersprungen")
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
    parser.add_argument("--skip-notifications",  action="store_true")
    parser.add_argument("--skip-monitors",       action="store_true")
    parser.add_argument("--skip-status-pages",   action="store_true")
    parser.add_argument("--dry-run",             action="store_true", help="Nur anzeigen, nicht importieren")
    args = parser.parse_args()

    print(f"📂 Lade Backup: {args.file}")
    try:
        backup = load_backup(args.file)
    except FileNotFoundError:
        print(f"❌ Datei nicht gefunden: {args.file}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ Ungültiges JSON: {e}")
        sys.exit(1)

    monitors      = backup.get("monitorList",      [])
    notifications = backup.get("notificationList", [])
    status_pages  = backup.get("statusPageList",   [])

    print(f"   Monitors:      {len(monitors)}")
    print(f"   Notifications: {len(notifications)}")
    print(f"   Status Pages:  {len(status_pages)}")

    if args.dry_run:
        print("\n⚠️  DRY-RUN Modus – es werden keine Daten verändert\n")

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