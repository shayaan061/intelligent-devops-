"""Background traffic for the demo app (SUGGESTED_PLAN.md §6.7).

The HTTP alert rules (HighLatency, HighErrorRate) and the ML detector need a
steady request rate: with no traffic the rates are NaN and nothing fires.
"""

from locust import HttpUser, between, task


class FrontendUser(HttpUser):
    wait_time = between(0.5, 1.5)

    @task
    def home(self):
        # Long timeout so injected 5s latency shows up as latency, not client errors
        self.client.get("/", timeout=15)
