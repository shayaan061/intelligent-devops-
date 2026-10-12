"""ML anomaly detector service (SUGGESTED_PLAN.md §6.2).

Every POLL_SECONDS it reads each service's features from Prometheus with the
gateway's context queries (gateway/context.py, which asserts no fault_*
query), scores them with the trained models (model.py, train.py) and, once a
service has been anomalous for SUSTAIN polls in a row, POSTs
{"service", "score", "top_features", "timestamp"} to the gateway's
/anomalies. It re-posts every poll while the anomaly lasts: the gateway
treats a repeat as a refresh (no new analysis), keeps the incident open, and
the verifier reads it back as `ml_active`. When the poll is normal again it
simply stops posting.

The detector only reports. Like the analyzer it never acts.

Env: PROMETHEUS_URL, GATEWAY_URL, MODEL_PATH, POLL_SECONDS (15), SUSTAIN (2).
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

import httpx
import joblib

HERE = os.path.dirname(os.path.abspath(__file__))
for p in (os.path.join(HERE, "..", "gateway"), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

from context import SERVICE_QUERIES, clean  # noqa: E402  (asserts: no fault_* query)
from model import FEATURES  # noqa: E402

PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090").rstrip("/")
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000").rstrip("/")
MODEL_PATH = os.environ.get("MODEL_PATH", os.path.join(HERE, "models", "detector.joblib"))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", "15"))
SUSTAIN = int(os.environ.get("SUSTAIN", "2"))

log = logging.getLogger("ml-detector")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def read_features(client, service):
    sample = {}
    for f in FEATURES[service]:
        q = SERVICE_QUERIES[service][f].format(s=service)
        r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
        r.raise_for_status()
        result = r.json()["data"]["result"]
        sample[f] = clean(result[0]["value"][1]) if result else None
    return sample


class Detector:
    def __init__(self, models, sustain=SUSTAIN):
        self.models = models
        self.sustain = sustain
        self.streak = {svc: 0 for svc in models}

    def step(self, service, sample):
        """Score one poll. Returns the anomaly to report, or None."""
        res = self.models[service].score(sample)
        self.streak[service] = self.streak[service] + 1 if res["anomalous"] else 0
        if self.streak[service] < self.sustain:
            return None
        return {"service": service, "score": res["score"], "top_features": res["top_features"],
                "z": {f: res["z"][f] for f in res["top_features"]}}


async def poll_once(client, det):
    for svc in det.models:
        try:
            sample = await read_features(client, svc)
        except Exception as e:
            log.warning("prometheus read failed for %s: %s", svc, e)
            continue
        anomaly = det.step(svc, sample)
        if anomaly is None:
            continue
        body = {k: anomaly[k] for k in ("service", "score", "top_features")}
        body["timestamp"] = now_iso()
        log.info("ANOMALY %s score=%s z=%s", svc, anomaly["score"], anomaly["z"])
        try:
            r = await client.post(f"{GATEWAY_URL}/anomalies", json=body)
            if r.status_code >= 300:
                log.warning("POST /anomalies -> %s %s", r.status_code, r.text[:200])
        except Exception as e:
            log.warning("gateway unreachable: %s", e)


async def wait_for_model():
    if not os.path.exists(MODEL_PATH):
        log.warning("no model at %s yet; train it with train.py (waiting)", MODEL_PATH)
    while not os.path.exists(MODEL_PATH):
        await asyncio.sleep(30)


async def serve():
    await wait_for_model()
    bundle = joblib.load(MODEL_PATH)
    det = Detector(bundle["models"])
    log.info("loaded %s (trained on %s, window %s)", MODEL_PATH,
             bundle["report"]["sources"], bundle["report"]["window"])
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            started = asyncio.get_running_loop().time()
            await poll_once(client, det)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0.0, POLL_SECONDS - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per query otherwise
    asyncio.run(serve())
