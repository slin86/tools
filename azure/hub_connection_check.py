import subprocess
import json
import urllib.request

SUBSCRIPTION = "07fbfdf7-216c-4ee7-a349-76309b7dd5bc"
RG = "Geofox"
HUB_NAME = "virtual-wan-hub"

TOKEN = subprocess.run(
    ["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
    capture_output=True, text=True
).stdout.strip()

url = (
    f"https://management.azure.com/subscriptions/{SUBSCRIPTION}"
    f"/resourceGroups/{RG}/providers/Microsoft.Network/virtualHubs/{HUB_NAME}"
    f"/hubVirtualNetworkConnections?api-version=2024-01-01"
)

req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
with urllib.request.urlopen(req) as r:
    result = json.loads(r.read())

for conn in result["value"]:
    name = conn["name"]
    state = conn["properties"].get("provisioningState", "unknown")
    print(f"🔹 {name}: {state}")