"""Executor (§6.5): the only code in the system that changes anything.

Implements exactly the allowlisted action types, through the Docker SDK
and the services' /reset endpoint. No shell commands are built from plan
text. The allowlist is checked again here (defence in depth), so a bug in
the validator can't widen what runs.

  reset_faults       POST <service>/reset
  restart_container  docker restart <name> (also starts a stopped container)
  flush_cache        redis-cli FLUSHALL inside the redis container (approval only)
  update_resources   not implemented: plans carry no limits to set
  escalate           nothing to execute; recorded by the caller
"""

import asyncio
import logging
import os

import httpx

log = logging.getLogger("responder.executor")

SERVICE_URLS = {
    "frontend": os.environ.get("FRONTEND_URL", "http://localhost:5001"),
    "api-service": os.environ.get("API_SERVICE_URL", "http://localhost:5002"),
}


class Executor:
    def __init__(self, policies, docker_client=None, transport=None):
        self.policies = policies
        self.docker = docker_client
        self.transport = transport  # tests inject httpx.MockTransport

    def allowed(self, action):
        a_type, target = action.get("type"), action.get("target")
        if not isinstance(a_type, str) or not isinstance(target, str):
            return False
        rule = self.policies["actions"].get(a_type)
        return rule is not None and target in rule["targets"]

    async def run(self, action):
        """Returns (ok, detail)."""
        a_type, target = action.get("type"), action.get("target")
        if not self.allowed(action) or a_type == "escalate":
            return False, f"refused: {a_type} on {target} is not executable"
        try:
            if a_type == "reset_faults":
                return await self._reset(target)
            if a_type == "restart_container":
                return await asyncio.to_thread(self._restart, target)
            if a_type == "flush_cache":
                return await asyncio.to_thread(self._flush, target)
            return False, f"{a_type} is not implemented"
        except Exception as e:
            log.exception("%s on %s failed", a_type, target)
            return False, f"{e.__class__.__name__}: {e}"

    async def _reset(self, target):
        async with httpx.AsyncClient(timeout=5, transport=self.transport) as client:
            r = await client.post(f"{SERVICE_URLS[target]}/reset")
        if r.status_code >= 300:
            return False, f"/reset -> {r.status_code}"
        return True, "faults reset"

    def _container(self, name):
        if self.docker is None:
            raise RuntimeError("docker socket not available")
        return self.docker.containers.get(name)

    def _restart(self, target):
        self._container(target).restart(timeout=10)
        return True, "container restarted"

    def _flush(self, target):
        result = self._container(target).exec_run(["redis-cli", "FLUSHALL"])
        if result.exit_code != 0:
            return False, f"FLUSHALL exit {result.exit_code}"
        return True, "cache flushed"
