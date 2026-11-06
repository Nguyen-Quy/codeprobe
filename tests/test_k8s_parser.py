from __future__ import annotations

from codeprobe.core.infra.k8s import HelmTemplateNeutralizer, K8sManifestParser


def test_helm_template_neutralizer():
    helm_yaml = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-backend
  labels:
    app.kubernetes.io/name: {{ include "mychart.name" . }}
spec:
  replicas: {{ .Values.replicaCount }}
  {{- if .Values.autoscaling.enabled }}
  # autoscaling block
  {{- end }}
  template:
    spec:
      containers:
        - name: app
          image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
          env:
            - name: DATABASE_URL
              value: {{ .Values.dbUrl | quote }}
"""
    neutralized = HelmTemplateNeutralizer.neutralize(helm_yaml)
    assert "# HELM_DIRECTIVE:" in neutralized
    assert "{{- if" not in neutralized
    assert "__HELM_VALUE__" in neutralized

    # Should now parse cleanly with K8sManifestParser
    units = K8sManifestParser.parse(
        helm_yaml, file_path="charts/backend/deployment.yaml"
    )
    assert len(units) >= 1
    assert units[0].kind == "k8s_deployment"


def test_k8s_multi_document_service_and_deployment():
    k8s_manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: prod
  labels:
    app: api-server
spec:
  replicas: 3
  template:
    metadata:
      labels:
        app: api-server
        tier: backend
    spec:
      containers:
        - name: web
          image: myorg/api:v1.2
          env:
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: db-credentials
                  key: password
            - name: CACHE_HOST
              valueFrom:
                configMapKeyRef:
                  name: redis-config
                  key: host
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: api-data-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: api-service
  namespace: prod
spec:
  selector:
    app: api-server
    tier: backend
  ports:
    - name: http
      port: 80
      targetPort: 8080
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: redis-config
data:
  host: "redis.prod.svc.cluster.local"
  port: "6379"
---
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
type: Opaque
stringData:
  password: "supersecretpassword"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: api-data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
"""
    units = K8sManifestParser.parse(k8s_manifest, file_path="deploy/k8s/api.yaml")
    by_name = {u.name: u for u in units}

    assert "api-server" in by_name
    assert "api-service" in by_name
    assert "redis-config" in by_name
    assert "db-credentials" in by_name
    assert "api-data-pvc" in by_name

    dep = by_name["api-server"]
    assert dep.kind == "k8s_deployment"
    assert "db-credentials" in dep.calls
    assert "redis-config" in dep.calls
    assert "api-data-pvc" in dep.calls
    assert "DB_PASSWORD" in dep.calls

    svc = by_name["api-service"]
    assert svc.kind == "k8s_service"
    # Service selector app=api-server, tier=backend matches Deployment api-server!
    assert "api-server" in svc.calls

    cm = by_name["redis-config"]
    assert cm.kind == "k8s_configmap"
    assert "host" in cm.calls
    assert "port" in cm.calls

    sec = by_name["db-credentials"]
    assert sec.kind == "k8s_secret"
    assert "password" in sec.calls

    pvc = by_name["api-data-pvc"]
    assert pvc.kind == "k8s_pvc"
    assert "10Gi" in pvc.signature


def test_k8s_network_policy_linking():
    k8s_manifest = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
spec:
  template:
    metadata:
      labels:
        role: payment
    spec:
      containers:
        - name: app
          image: payment:v1
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend-service
spec:
  template:
    metadata:
      labels:
        role: frontend
    spec:
      containers:
        - name: app
          image: frontend:v1
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-payment
spec:
  podSelector:
    matchLabels:
      role: payment
  ingress:
    - from:
        - podSelector:
            matchLabels:
              role: frontend
"""
    units = K8sManifestParser.parse(k8s_manifest, file_path="deploy/netpol.yaml")
    by_name = {u.name: u for u in units}

    assert "allow-frontend-to-payment" in by_name
    netpol = by_name["allow-frontend-to-payment"]
    assert netpol.kind == "k8s_networkpolicy"
    # Matches target payment-service and ingress source frontend-service!
    assert "payment-service" in netpol.calls
    assert "frontend-service" in netpol.calls
