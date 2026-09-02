#!/usr/bin/env python3
"""
Exports all key/value secrets into json File.

Requirements:
    pip install hvac

Usage:
    Fill in the CONFIG section below, then run:
    python vault_export.py
"""

import json
import sys

import hvac

# ---------------------------------------------------------------------------
# CONFIG - edit these values
# ---------------------------------------------------------------------------
VAULT_ADDR = "https://vault.hochbahn.cloud"
VAULT_TOKEN = ""
VAULT_MOUNT = "kv"
KV_VERSION = 2
BASE_PATH = "/infra/dev/"
OUTPUT_FILE = "vault_export-infra.json"
INCLUDE_METADATA = True
VERIFY_TLS = True
# ---------------------------------------------------------------------------


def list_all_paths(client, mount, base_path, kv_version):
    try:
        if kv_version == 2:
            resp = client.secrets.kv.v2.list_secrets(path=base_path, mount_point=mount)
        else:
            resp = client.secrets.kv.v1.list_secrets(path=base_path, mount_point=mount)
    except hvac.exceptions.InvalidPath:
        return

    keys = resp.get("data", {}).get("keys", [])
    for key in keys:
        full_path = f"{base_path}{key}" if base_path.endswith("/") or base_path == "" else f"{base_path}/{key}"
        if key.endswith("/"):
            # It's a "folder" -> recurse
            yield from list_all_paths(client, mount, full_path, kv_version)
        else:
            yield full_path


def read_secret(client, mount, path, kv_version):
    if kv_version == 2:
        resp = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
        return resp["data"]["data"], resp["data"]["metadata"]
    else:
        resp = client.secrets.kv.v1.read_secret(path=path, mount_point=mount)
        return resp["data"], None


def main():
    if not VAULT_ADDR or not VAULT_TOKEN:
        sys.exit("Error: VAULT_ADDR and VAULT_TOKEN must be set in the CONFIG section.")

    client = hvac.Client(url=VAULT_ADDR, token=VAULT_TOKEN, verify=VERIFY_TLS)

    if not client.is_authenticated():
        sys.exit("Error: Vault authentication failed. Please check the token.")

    print(f"Connected to {VAULT_ADDR}, mount '{VAULT_MOUNT}' (KV v{KV_VERSION}), base path '{BASE_PATH}'")
    print("Collecting paths...")

    paths = list(list_all_paths(client, VAULT_MOUNT, BASE_PATH, KV_VERSION))
    print(f"Found {len(paths)} secrets. Reading contents...")

    export_data = {}
    errors = []

    for i, path in enumerate(paths, start=1):
        try:
            data, metadata = read_secret(client, VAULT_MOUNT, path, KV_VERSION)
            if INCLUDE_METADATA and metadata is not None:
                export_data[path] = {"data": data, "metadata": metadata}
            else:
                export_data[path] = data
        except Exception as e:
            errors.append((path, str(e)))
            print(f"  Warning: could not read '{path}': {e}")

        if i % 25 == 0 or i == len(paths):
            print(f"  {i}/{len(paths)} processed")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(export_data, f, indent=2, ensure_ascii=False, sort_keys=True)

    print(f"\nDone. {len(export_data)} secrets exported to '{OUTPUT_FILE}'.")
    if errors:
        print(f"{len(errors)} secrets could not be read (see warnings above).")
        print("Likely cause: missing read permission for those specific paths.")


if __name__ == "__main__":
    main()