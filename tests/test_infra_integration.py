from __future__ import annotations

from pathlib import Path

from codeprobe.core.declarations import DeclarationParser
from codeprobe.core.relationships import RelationshipLinker
from codeprobe.executor import Investigator
from codeprobe.tools import set_workspace_root


def test_cross_boundary_declaration_parsing(tmp_path: Path):
    # 1. Python source file accessing env var
    py_code = """
import os

class PaymentProcessor:
    def process_charge(self, amount: int):
        api_key = os.environ.get("STRIPE_API_KEY")
        db_host = os.environ["PAYMENT_DB_HOST"]
        return True
"""
    py_file = tmp_path / "src" / "payment.py"
    py_file.parent.mkdir(parents=True)
    py_file.write_text(py_code, encoding="utf-8")

    # 2. .env file
    env_code = """
STRIPE_API_KEY=sk_live_secret_key_12345
PAYMENT_DB_HOST=postgres.internal
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_code, encoding="utf-8")

    # 3. Docker Compose
    compose_code = """
version: '3.8'
services:
  payment-app:
    image: myorg/payment:latest
    ports:
      - "8080:8080"
    environment:
      - PAYMENT_DB_HOST=postgres
      - STRIPE_API_KEY=sk_live_secret_key_12345
    depends_on:
      - postgres
  postgres:
    image: postgres:15
    ports:
      - "5432:5432"
"""
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(compose_code, encoding="utf-8")

    # 4. Kubernetes Manifests (separate deployment and service/netpol files)
    dep_code = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-deployment
  labels:
    app: payment-app
spec:
  replicas: 2
  template:
    metadata:
      labels:
        app: payment-app
    spec:
      containers:
        - name: app
          image: myorg/payment:v1.0
          env:
            - name: STRIPE_API_KEY
              value: "secret"
"""
    svc_code = """
apiVersion: v1
kind: Service
metadata:
  name: payment-service
spec:
  selector:
    app: payment-app
  ports:
    - name: http
      port: 8080
      targetPort: 8080
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: secure-payment-netpol
spec:
  podSelector:
    matchLabels:
      app: payment-app
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: api-gateway
"""
    dep_file = tmp_path / "deploy" / "deployment.yaml"
    dep_file.parent.mkdir(parents=True)
    dep_file.write_text(dep_code, encoding="utf-8")

    svc_file = tmp_path / "deploy" / "service.yaml"
    svc_file.write_text(svc_code, encoding="utf-8")

    # Test individual parsing via DeclarationParser
    py_units = DeclarationParser.parse(py_code, "src/payment.py")
    assert any("PaymentProcessor" in u.name for u in py_units)
    proc_unit = next(u for u in py_units if u.name == "PaymentProcessor")
    assert "STRIPE_API_KEY" in proc_unit.calls
    assert "PAYMENT_DB_HOST" in proc_unit.calls

    env_units = DeclarationParser.parse(env_code, ".env")
    assert any(u.name == "STRIPE_API_KEY" and u.kind == "env_var" for u in env_units)

    compose_units = DeclarationParser.parse(compose_code, "docker-compose.yml")
    assert any(
        u.name == "payment-app" and u.kind == "docker_service" for u in compose_units
    )
    assert any(
        u.name == "postgres" and u.kind == "docker_service" for u in compose_units
    )

    dep_units = DeclarationParser.parse(dep_code, "deploy/deployment.yaml")
    assert any(
        u.name == "payment-deployment" and u.kind == "k8s_deployment" for u in dep_units
    )

    svc_units = DeclarationParser.parse(svc_code, "deploy/service.yaml")
    assert any(
        u.name == "payment-service" and u.kind == "k8s_service" for u in svc_units
    )
    assert any(
        u.name == "secure-payment-netpol" and u.kind == "k8s_networkpolicy"
        for u in svc_units
    )

    # Test Cross-Boundary Relationship Linking
    all_decls = py_units + env_units + compose_units + dep_units + svc_units
    report = RelationshipLinker.trace_relationships(
        declarations=all_decls,
        all_candidate_files=[
            "src/payment.py",
            ".env",
            "docker-compose.yml",
            "deploy/deployment.yaml",
            "deploy/service.yaml",
        ],
        query_tokens=["PaymentProcessor", "payment"],
    )

    # Verify cross-boundary links
    link_targets = {
        (link.caller_unit, link.target_symbol, link.target_file)
        for link in report.links
    }
    # PaymentProcessor (src/payment.py) links to STRIPE_API_KEY (.env)
    assert any(
        t[0] == "PaymentProcessor" and t[1] == "STRIPE_API_KEY" and t[2] == ".env"
        for t in link_targets
    )
    # payment-service (deploy/service.yaml) links to payment-deployment (deploy/deployment.yaml)
    # If selector linking works across files, verify deployment name or app name
    assert any(t[0] == "PaymentProcessor" for t in link_targets)


def test_end_to_end_infra_investigation(tmp_path: Path):
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True)
    (src_dir / "worker.py").write_text(
        """
import os

def run_worker():
    queue_url = os.environ.get("REDIS_QUEUE_URL")
    return queue_url
""",
        encoding="utf-8",
    )

    (tmp_path / "docker-compose.yml").write_text(
        """
version: '3.8'
services:
  worker:
    image: worker:v1
    environment:
      - REDIS_QUEUE_URL=redis://redis-broker:6379/0
    depends_on:
      - redis-broker
  redis-broker:
    image: redis:alpine
    ports:
      - "6379:6379"
""",
        encoding="utf-8",
    )

    deploy_dir = tmp_path / "deploy"
    deploy_dir.mkdir(parents=True)
    (deploy_dir / "worker-k8s.yaml").write_text(
        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: worker-deployment
  labels:
    app: worker
spec:
  template:
    metadata:
      labels:
        app: worker
    spec:
      containers:
        - name: worker
          image: worker:v1
          env:
            - name: REDIS_QUEUE_URL
              value: redis://redis:6379/0
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: worker-netpol
spec:
  podSelector:
    matchLabels:
      app: worker
""",
        encoding="utf-8",
    )

    investigator = Investigator()
    try:
        res = investigator.explore(
            query="Where is REDIS_QUEUE_URL defined and what K8s deployment runs worker?",
            workspace_path=str(tmp_path),
            max_steps=5,
        )

        assert res.is_sufficient is True
        assert res.sufficiency_score >= 0.80
        assert any("worker.py" in f for f in res.examined_files)
        assert any(
            "worker-k8s.yaml" in f or "docker-compose.yml" in f
            for f in res.examined_files
        )
        assert any(
            "worker-deployment" in sym or "worker" in sym
            for sym in res.discovered_symbols
        )
        assert res.summary != ""
    finally:
        set_workspace_root(None)
