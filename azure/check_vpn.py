import subprocess
import json

SUBSCRIPTION = "07fbfdf7-216c-4ee7-a349-76309b7dd5bc"
RG = "Geofox"

# Token holen
token_result = subprocess.run(
    ["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True
)
TOKEN = token_result.stdout.strip()

# HTTP Helper
import urllib.request

def az_get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# 1. VPN Gateways auflisten
gateways = az_get(
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
    f"/resourceGroups/{RG}/providers/Microsoft.Network/vpnGateways"
    f"?api-version=2024-01-01"
)

for gw in gateways["value"]:
    gw_name = gw["name"]
    print(f"\n🔹 Gateway: {gw_name}")

    # 2. Connections auflisten
    connections = az_get(
        f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
        f"/resourceGroups/{RG}/providers/Microsoft.Network/vpnGateways/{gw_name}/vpnConnections"
        f"?api-version=2024-01-01"
    )

    for conn in connections["value"]:
        print(f"  📡 Connection: {conn['name']}")
        for link in conn.get("properties", {}).get("vpnLinkConnections", []):
            shared_key = link.get("properties", {}).get("sharedKey", "⚠️  LEER")
            print(f"    🔑 Link: {link['name']} → SharedKey: {shared_key}")