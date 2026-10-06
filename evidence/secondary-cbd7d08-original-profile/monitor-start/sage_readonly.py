import json

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://127.0.0.1:9257"
CERT = (
    r"C:\Users\M920q\AppData\Roaming\com.rigidnetwork.sage\ssl\wallet.crt",
    r"C:\Users\M920q\AppData\Roaming\com.rigidnetwork.sage\ssl\wallet.key",
)


def rpc(name, payload):
    response = requests.post(
        f"{BASE_URL}/{name}",
        json=payload,
        cert=CERT,
        verify=False,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


key = rpc("get_key", {})
sync = rpc("get_sync_status", {})
pending = rpc("get_pending_transactions", {})
offers = rpc("get_offers", {"include_completed": False, "start": 0, "end": 5000})

offer_rows = offers.get("offers") or offers.get("trade_records") or []
status_counts = {}
for row in offer_rows:
    status = str(row.get("status", "unknown")).lower()
    status_counts[status] = status_counts.get(status, 0) + 1
fillable = sum(
    count
    for status, count in status_counts.items()
    if status not in {"cancelled", "canceled", "expired", "completed", "confirmed"}
)

print(
    json.dumps(
        {
            "key": key,
            "sync": sync,
            "pending_count": len(
                pending.get("transactions")
                or pending.get("pending_transactions")
                or []
            ),
            "offer_total": len(offer_rows),
            "offer_status_counts": status_counts,
            "fillable_count": fillable,
        },
        indent=2,
    )
)
