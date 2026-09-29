#!/usr/bin/env python3
"""
Uptime Kuma v1 JSON Export → v2 Import

Importiert Monitors, Notifications und Status Pages aus einem v1-Backup in v2.

Gegenüber der ursprünglichen Version behoben:
  1. Notifications wurden bisher pauschal ALLEN Monitoren zugewiesen
     (all_notification_ids = alle importierten Notifications). Jetzt wird
     pro Monitor die v1-eigene notificationIDList ausgewertet und nur die
     dort tatsächlich aktivierten (True) Notifications werden übernommen.
  2. Monitore vom Typ "group" (Ordner) hatten in vielen v1-Backups
     "interval"/"retryInterval" explizit auf null stehen. `m.get("interval", 60)`
     liefert in dem Fall trotzdem None (der Default greift nur, wenn der Key
     GANZ FEHLT, nicht wenn er auf null steht) -> max(None, 20) crashte mit
     TypeError. Dadurch schlug das Anlegen der Gruppe fehl, old_id_to_new_id
     bekam nie einen Eintrag für die Gruppe, und ALLE Kind-Monitore dieser
     Gruppe verloren in der Folge ihre Ordner-Zuordnung ("Parent-ID nicht
     gemappt"). Jetzt werden None-Werte explizit vor dem max() abgefangen.
  3. Fehlermeldungen loggen jetzt zusätzlich den Exception-Typ, damit sowas
     beim nächsten Mal sofort auffällt statt nur "Ordner fehlen" zu zeigen.

Abhängigkeiten:
    pip install uptime-kuma-api-v2

Verwendung:
    python kuma_import_v2_fixed.py \
        --file backup.json \
        --url http://localhost:3001 \
        --username admin \
        --password secret

    # Dry-Run (kein tatsächlicher Import):
    python kuma_import_v2_fixed.py --file backup.json --url ... --dry-run

    # Nur Monitors importieren:
    python kuma_import_v2_fixed.py --file backup.json --url ... --skip-notifications --skip-status-pages
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


def _int_or_default(value, default):
    """Wie .get(key, default), aber behandelt auch explizite null-Werte
    (z.B. bei Gruppen-Monitoren) als 'nicht gesetzt'."""
    return default if value is None else value


def build_monitor_kwargs(m: dict) -> dict:
    """Extrahiert alle relevanten Felder aus einem v1-Monitor-Objekt.
    Typen werden als rohe Strings übergeben – keine Enum-Konvertierung nötig.
    """
    interval = _int_or_default(m.get("interval"), 60)
    retry_interval = _int_or_default(m.get("retryInterval"), 60)

    kwargs = {
        "type":          m.get("type", "http"),   # String direkt, kein Enum
        "name":          m.get("name", "Unnamed"),
        "interval":      max(interval, 20),
        "retryInterval": max(retry_interval, 20),
        "maxretries":    _int_or_default(m.get("maxretries"), 0),
        "upsideDown":    _int_or_default(m.get("upsideDown"), False),
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


def monitor_notification_ids(m: dict) -> list:
    """Liest die in v1 pro Monitor aktivierten Notification-IDs aus.
    v1 speichert das als Dict {"<notif_id>": true/false}."""
    raw = m.get("notificationIDList", {})
    if isinstance(raw, dict):
        ids = []
        for k, enabled in raw.items():
            if not enabled:
                continue
            try:
                ids.append(int(k))
            except (TypeError, ValueError):
                pass
        return ids
    if isinstance(raw, list):
        return raw
    return []


# ---------------------------------------------------------------------------
# Import-Funktionen
# ---------------------------------------------------------------------------

def import_notifications(api: UptimeKumaApi, notifications: list, dry_run: bool):
    """Gibt zwei Mappings zurück:
       - name_to_new_id: alter Name -> neue ID (für spätere Verwendung)
       - old_id_to_name: alte v1-Notification-ID -> Name (um Monitor-Zuordnungen aufzulösen)
    """
    name_to_new_id = {}
    old_id_to_name = {}
    print(f"\n📣 Notifications: {len(notifications)} gefunden")

    for n in notifications:
        name = n.get("name", "Unnamed")
        old_id = n.get("id")
        if old_id is not None:
            old_id_to_name[old_id] = name

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
                print(f"     ❌ Fehler ({type(e).__name__}): {e}")
        else:
            print(f"     [DRY-RUN] Würde erstellt werden")

    return name_to_new_id, old_id_to_name


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
    notification_old_id_to_name: dict,
    dry_run: bool,
) -> dict:
    """Importiert Monitors in topologischer Reihenfolge (Parents vor Kindern).
    Gibt Mapping zurück: alte ID → neue ID"""
    old_id_to_new_id = {}
    print(f"\n🖥️  Monitors: {len(monitors)} gefunden")

    ordered = topological_sort(monitors)

    for m in ordered:
        kwargs = build_monitor_kwargs(m)
        name   = kwargs["name"]

        # --- Notifications: nur die pro Monitor tatsächlich aktivierten ---
        enabled_old_ids = monitor_notification_ids(m)
        new_notif_ids = []
        for old_nid in enabled_old_ids:
            notif_name = notification_old_id_to_name.get(old_nid)
            if notif_name is None:
                continue
            new_nid = notification_name_to_id.get(notif_name)
            if new_nid is not None:
                new_notif_ids.append(new_nid)
        if new_notif_ids:
            kwargs["notificationIDList"] = new_notif_ids

        # --- Parent-Gruppe zuordnen ---
        parent_old_id = m.get("parent")
        if parent_old_id is not None:
            if parent_old_id in old_id_to_new_id:
                kwargs["parent"] = old_id_to_new_id[parent_old_id]
            elif dry_run:
                print(f"     [DRY-RUN] Parent-ID {parent_old_id} wird im echten Lauf gemappt")
            else:
                print(f"     ⚠️  Parent-ID {parent_old_id} nicht gemappt (Parent evtl. nicht erfolgreich angelegt?), wird ignoriert")

        print(f"  → Monitor: '{name}' (Typ: {m.get('type', '?')})")

        if not dry_run:
            try:
                result = api.add_monitor(**kwargs)
                new_id = result.get("monitorID")
                if "id" in m:
                    old_id_to_new_id[m["id"]] = new_id
                print(f"     ✅ Erstellt mit ID {new_id}")
                time.sleep(0.3)
            except Exception as e:
                print(f"     ❌ Fehler bei '{name}' ({type(e).__name__}): {e}")
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
                print(f"     ❌ Fehler bei '{title}' ({type(e).__name__}): {e}")
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

    # Uncomment, if
    # xsrf_value = "..."
    # session_value = "..."
    # filter_value = "..."
    #
    # extra_headers = {
    #     "Cookie": f"ambassador_session.{filter_value}.ambassador={session_value}; "
    #               f"ambassador_xsrf.{filter_value}.ambassador={xsrf_value}",
    #     "X-XSRF-Token": xsrf_value,
    # }

    print(f"\n🔌 Verbinde mit {args.url} ...")
    try:

        with UptimeKumaApi(args.url, headers=extra_headers or None) as api:
            api.login(args.username, args.password)
            print("✅ Login erfolgreich\n")

            notification_name_to_id = {}
            notification_old_id_to_name = {}
            monitor_old_to_new_id   = {}

            if not args.skip_notifications:
                notification_name_to_id, notification_old_id_to_name = import_notifications(
                    api, notifications, args.dry_run
                )

            if not args.skip_monitors:
                monitor_old_to_new_id = import_monitors(
                    api, monitors, notification_name_to_id, notification_old_id_to_name, args.dry_run
                )

            if not args.skip_status_pages:
                import_status_pages(api, status_pages, monitor_old_to_new_id, args.dry_run)

    except Exception as e:
        print(f"\n❌ Verbindungsfehler ({type(e).__name__}): {e}")
        sys.exit(1)

    print("\n🎉 Import abgeschlossen!")


if __name__ == "__main__":
    main()