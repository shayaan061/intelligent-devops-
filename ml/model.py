"""Anomaly model for the ML detector (SUGGESTED_PLAN.md §6.2).

One model per service, trained on normal traffic only
(experiments/record_baseline.py). Two parts, both explainable:

1. Robust z-score per metric against the training baseline:
   z = (x - median) / scale, with scale = max(1.4826 * MAD, floor). The
   floor stops a metric that never moves in training (err = 0) from making
   every tiny wobble look infinite. Only the direction that means trouble
   counts (HIGH_IS_BAD: more CPU, memory, latency, errors); a restarted
   container using *less* memory than usual is not an incident.
2. Isolation Forest over the whole z-vector, so combinations that no single
   metric shows are scored too. Its threshold is a high quantile of the
   training scores.

A sample is anomalous when
  - a HIGH_IS_BAD metric has z >= z_threshold (a clear single-metric
    deviation; the forest alone scores these weakly, because a value far
    outside the training range in one dimension is not isolated much faster
    than the training tail), or
  - the forest flags it AND a HIGH_IS_BAD metric has z >= z_soft (moderate
    deviations in several metrics at once, e.g. a little more latency and a
    few errors; the z_soft gate keeps "lower than usual" out).
top_features are the HIGH_IS_BAD metrics with z >= z_soft, largest first
(the runbook `ml-memory-anomaly` matches any entry containing "mem").

The detector (detector.py) adds persistence: an anomaly is reported only
after `sustain` consecutive anomalous polls (plan §13, ML false positives).

Never train on or score fault_*_active: features come from gateway/context.py,
whose import-time assert rejects fault_* queries.
"""

import math

import numpy as np
from sklearn.ensemble import IsolationForest

# Per-service features: the context queries minus `up` (down is the rules' job)
FEATURES = {
    "frontend": ["cpu", "mem", "p95", "err", "rps", "upstream_p95"],
    "api-service": ["cpu", "mem", "p95", "err", "rps", "upstream_p95"],
    "redis": ["mem", "mem_bytes", "clients", "ops"],
}

HIGH_IS_BAD = {"cpu", "mem", "p95", "err", "upstream_p95", "mem_bytes", "clients"}

# Smallest scale per metric, in its own unit (ratio, seconds, bytes, req/s)
FLOOR = {"cpu": 0.05, "mem": 0.02, "p95": 0.05, "err": 0.02, "upstream_p95": 0.05,
         "rps": 0.5, "ops": 0.5, "mem_bytes": 2 * 2**20, "clients": 2.0}

Z_CLIP = 50.0


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


class ServiceModel:
    def __init__(self, service, z_threshold=4.0, z_soft=2.0, if_quantile=0.995, seed=0):
        self.service = service
        self.features = FEATURES[service]
        self.z_threshold = z_threshold
        self.z_soft = z_soft
        self.if_quantile = if_quantile
        self.seed = seed

    def fit(self, rows):
        """rows: dicts with the feature names (None = missing)."""
        X = np.array([[_num(r.get(f)) if _num(r.get(f)) is not None else np.nan for f in self.features]
                      for r in rows], dtype=float)
        if len(X) < 20:
            raise ValueError(f"{self.service}: need at least 20 normal samples, got {len(X)}")
        self.median = np.nanmedian(X, axis=0)
        self.median = np.where(np.isnan(self.median), 0.0, self.median)
        mad = np.nanmedian(np.abs(X - self.median), axis=0)
        mad = np.where(np.isnan(mad), 0.0, mad)
        floors = np.array([FLOOR[f] for f in self.features])
        self.scale = np.maximum(1.4826 * mad, floors)
        Z = self._z(X)
        self.forest = IsolationForest(n_estimators=200, contamination="auto", random_state=self.seed).fit(Z)
        scores = -self.forest.score_samples(Z)
        self.if_threshold = float(np.quantile(scores, self.if_quantile))
        self.n_train = len(X)
        return self

    def _z(self, X):
        X = np.where(np.isnan(X), self.median, X)  # missing = typical
        return np.clip((X - self.median) / self.scale, -Z_CLIP, Z_CLIP)

    def score(self, sample):
        """sample: {feature: value}. Returns dict(anomalous, score, top_features, z)."""
        x = np.array([[_num(sample.get(f)) if _num(sample.get(f)) is not None else np.nan
                       for f in self.features]], dtype=float)
        z = self._z(x)[0]
        if_score = float(-self.forest.score_samples(z.reshape(1, -1))[0])
        bad = sorted(((z[i], f) for i, f in enumerate(self.features)
                      if f in HIGH_IS_BAD and z[i] >= self.z_soft), reverse=True)
        strong = bool(bad) and bad[0][0] >= self.z_threshold
        forest = bool(bad) and if_score > self.if_threshold
        return {
            "anomalous": strong or forest,
            "by": [k for k, on in (("z", strong), ("forest", forest)) if on],
            "score": round(if_score, 3),
            "top_features": [f for _, f in bad],
            "z": {f: round(float(z[i]), 2) for i, f in enumerate(self.features)},
        }

    def summary(self):
        return {"service": self.service, "n_train": self.n_train, "if_threshold": round(self.if_threshold, 3),
                "median": dict(zip(self.features, np.round(self.median, 4).tolist())),
                "scale": dict(zip(self.features, np.round(self.scale, 4).tolist()))}


def fit_all(rows, **kw):
    """rows: record_baseline.py CSV rows (one per timestamp and service)."""
    models = {}
    for svc in FEATURES:
        svc_rows = [r for r in rows if r.get("service") == svc]
        models[svc] = ServiceModel(svc, **kw).fit(svc_rows)
    return models
