"""Create the quickstart payout. Run from a folder that holds payout.json."""

# docs:start
import json
import os
import urllib.request
import uuid

with open("payout.json", "rb") as f:
    body = f.read()
request = urllib.request.Request(
    os.environ["DEKERNAI_BASE_URL"] + "/v1/payment_intents",
    data=body,
    method="POST",
    headers={
        "Authorization": "Bearer " + os.environ["DEKERNAI_API_KEY"],
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(request) as response:
    payment = json.load(response)
print(payment["id"], payment["status"])
# docs:end
