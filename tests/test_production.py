import json
import os
import unittest
from unittest.mock import patch

os.environ["AIOPS_API_TOKEN"] = "t" * 64
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["PROMETHEUS_URL"] = "http://prometheus.example"
os.environ["PROMETHEUS_QUERIES"] = '{"cpu":"up"}'
os.environ["KUBERNETES_NAMESPACE"] = "test-namespace"

import app as service
from fastapi import HTTPException
from pydantic import ValidationError


class ProductionSecurityTests(unittest.TestCase):
    def test_bearer_token_is_required_and_constant_time_checked(self):
        with patch.object(service, "API_TOKEN", "s" * 64):
            with self.assertRaises(HTTPException) as missing:
                service.require_api_token(None)
            self.assertEqual(missing.exception.status_code, 401)
            with self.assertRaises(HTTPException) as incorrect:
                service.require_api_token("Bearer wrong")
            self.assertEqual(incorrect.exception.status_code, 401)
            service.require_api_token("Bearer " + "s" * 64)

    def test_agent_context_drops_pod_names_and_metric_labels(self):
        raw = {
            "application": "orders",
            "kubernetes": {"pods": [{"name": "sensitive-pod-name", "phase": "Running", "restarts": 2, "node": "private-node"}]},
            "metrics": {"cpu": [{"metric": {"pod": "sensitive-pod-name"}, "value": [1, "0.7"]}]},
        }
        context = service.agent_context(raw)
        serialized = json.dumps(context)
        self.assertNotIn("sensitive-pod-name", serialized)
        self.assertNotIn("private-node", serialized)
        self.assertEqual(context["pods"]["restarts"], 2)
        self.assertEqual(context["metrics"]["cpu"][0]["value"], "0.7")

    def test_question_rejects_unknown_fields(self):
        with self.assertRaises(ValidationError):
            service.Question.model_validate({"question": "check service", "execute_command": "kubectl delete pods --all"})

    def test_prometheus_namespace_placeholder_uses_configured_namespace(self):
        payload = json.dumps({"status": "success", "data": {"result": []}}).encode()
        with patch.object(service, "NAMESPACE", "test-namespace"), patch.object(service.urllib.request, "urlopen") as opened:
            response = opened.return_value.__enter__.return_value
            response.read.return_value = payload
            name, result = service._query_prometheus("cpu", 'up{namespace="{namespace}"}')
        request_url = opened.call_args.args[0]
        self.assertIn("test-namespace", request_url)
        self.assertEqual((name, result), ("cpu", []))


if __name__ == "__main__":
    unittest.main()
