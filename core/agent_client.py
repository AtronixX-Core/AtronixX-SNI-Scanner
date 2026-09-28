"""
AX-Scanner :: agent_client.py
Thin HTTP client used by the probe side to ask the backend Agent
(running on the target/"Germany" server) to spin up / tear down
ephemeral Reality test instances.
"""

import json
import urllib.error
import urllib.request

from core.config import AGENT_HTTP_TIMEOUT


class AgentError(Exception):
    pass


class AgentClient:
    def __init__(self, host, port, token):
        self.base_url = f"http://{host}:{port}"
        self.token = token

    def _post(self, path, payload, timeout=None):
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", "X-Auth-Token": self.token},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or AGENT_HTTP_TIMEOUT) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode()).get("error", str(e))
            except Exception:
                msg = str(e)
            raise AgentError(msg)
        except Exception as e:
            raise AgentError(str(e))

    def health(self):
        try:
            with urllib.request.urlopen(f"{self.base_url}/health", timeout=5) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            raise AgentError(str(e))

    def probe_clients(self):
        req = urllib.request.Request(f"{self.base_url}/probe/clients",
                                     headers={"X-Auth-Token": self.token})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read().decode()).get("clients", [])
        except Exception as e:
            raise AgentError(str(e))

    def probe_job(self, op, payload, timeout=15):
        """Runs one test on the connected probe client. Returns the data
        dict, or raises AgentError (kind in .kind: unavailable/timeout/failed)."""
        result = self._post("/probe/job", {"op": op, "payload": payload, "timeout": timeout},
                            timeout=timeout + 5)
        if not result.get("ok"):
            err = AgentError(result.get("error", "probe job failed"))
            err.kind = result.get("kind", "failed")
            raise err
        return result["data"]

    def spawn(self, sni, transport="tcp"):
        result = self._post("/spawn", {"sni": sni, "transport": transport})
        if "error" in result:
            raise AgentError(result["error"])
        return result

    def destroy(self, instance_id):
        result = self._post("/destroy", {"instance_id": instance_id})
        if "error" in result:
            raise AgentError(result["error"])
        return result
