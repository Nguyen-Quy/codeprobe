from __future__ import annotations

import logging
import re
from typing import Any, ClassVar

import yaml

from ...schemas import DeclarationUnit

logger = logging.getLogger(__name__)


class HelmTemplateNeutralizer:
    """
    Sanitizes Helm chart YAML manifests containing Go / Jinja template tags
    ({{ .Values... }}, {{- if ... }}, {{- end }}) into safe, valid YAML
    so standard PyYAML can parse them without crashing.
    """

    @classmethod
    def neutralize(cls, content: str) -> str:
        lines: list[str] = []
        for line in content.splitlines():
            # If line is entirely a Helm template control directive (if, else, end, with, range, define)
            if re.match(
                r"^\s*\{\{-?\s*(?:if|else|end|with|range|define|template|include|toYaml|nindent).*\}\}\s*$",
                line,
            ):
                indent = len(line) - len(line.lstrip())
                clean_dir = re.sub(r"\{\{-?|-?\}\}", "", line).strip()
                lines.append(" " * indent + f"# HELM_DIRECTIVE: {clean_dir}")
                continue

            # Replace unquoted template values like 'key: {{ .Values.foo }}' with safe placeholder string
            line_mod = re.sub(
                r"(:\s*)(\{\{.*?\}\})(\s*)$", r'\1"__HELM_VALUE__"\3', line
            )

            # Replace inline templates {{ ... }} inside unquoted values
            line_mod = re.sub(r"\{\{.*?\}\}", "__HELM_VALUE__", line_mod)

            lines.append(line_mod)

        return "\n".join(lines)


class K8sManifestParser:
    """
    Parses multi-document Kubernetes YAML manifests into standard DeclarationUnits,
    mapping selectors, services, deployments, configmaps, secrets, and network policies.
    """

    K8S_KINDS: ClassVar[dict[str, str]] = {
        "Service": "k8s_service",
        "Deployment": "k8s_deployment",
        "StatefulSet": "k8s_statefulset",
        "DaemonSet": "k8s_daemonset",
        "CronJob": "k8s_cronjob",
        "Job": "k8s_job",
        "ConfigMap": "k8s_configmap",
        "Secret": "k8s_secret",
        "NetworkPolicy": "k8s_networkpolicy",
        "PersistentVolumeClaim": "k8s_pvc",
        "Ingress": "k8s_ingress",
    }

    @classmethod
    def is_k8s_document(cls, doc: Any) -> bool:
        return isinstance(doc, dict) and "kind" in doc and "apiVersion" in doc

    @classmethod
    def parse(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        sanitized = HelmTemplateNeutralizer.neutralize(content)

        try:
            documents = list(yaml.safe_load_all(sanitized))
        except (yaml.YAMLError, OSError) as exc:
            logger.debug("Failed to parse YAML in %s: %s", file_path, exc)
            return []

        units: list[DeclarationUnit] = []
        doc_spans = cls._find_document_line_spans(content)

        # First pass: collect all resources and their labels/selectors
        deployments_by_labels: list[tuple[str, dict[str, str]]] = []
        parsed_docs: list[tuple[dict, int, int]] = []

        doc_idx = 0
        for doc in documents:
            if not cls.is_k8s_document(doc):
                continue

            start_line, end_line = (
                doc_spans[doc_idx]
                if doc_idx < len(doc_spans)
                else (1, len(content.splitlines()))
            )
            doc_idx += 1
            parsed_docs.append((doc, start_line, end_line))

            kind = doc.get("kind", "")
            meta = doc.get("metadata", {}) or {}
            name = meta.get("name", "")

            # If workload with template labels, record for selector matching
            if kind in ("Deployment", "StatefulSet", "DaemonSet"):
                spec = doc.get("spec", {}) or {}
                template = spec.get("template", {}) or {}
                t_meta = template.get("metadata", {}) or {}
                labels = t_meta.get("labels", {}) or meta.get("labels", {}) or {}
                if isinstance(labels, dict) and name:
                    deployments_by_labels.append(
                        (name, {str(k): str(v) for k, v in labels.items()})
                    )

        # Second pass: build DeclarationUnits with cross-resource linkages
        for doc, start_line, end_line in parsed_docs:
            kind = doc.get("kind", "")
            meta = doc.get("metadata", {}) or {}
            spec = doc.get("spec", {}) or {}
            name = str(meta.get("name", f"unnamed-{kind.lower()}"))
            namespace = str(meta.get("namespace", "default"))
            labels = meta.get("labels", {}) or {}

            unit_kind = cls.K8S_KINDS.get(kind, f"k8s_{kind.lower()}")
            calls: list[str] = []
            doc_parts: list[str] = [f"Kind: {kind} | Namespace: {namespace}"]

            if labels and isinstance(labels, dict):
                doc_parts.append(
                    f"Labels: {', '.join(f'{k}={v}' for k, v in labels.items())}"
                )

            signature = f"{kind} {name}"

            if kind == "Service":
                selector = spec.get("selector", {}) or {}
                ports = spec.get("ports", []) or []
                port_strs = [
                    f"{p.get('name', 'port')}:{p.get('port')}->{p.get('targetPort', p.get('port'))}"
                    for p in ports
                    if isinstance(p, dict)
                ]
                signature = f"Service {name} ({', '.join(port_strs)})"
                if selector and isinstance(selector, dict):
                    sel_str = ", ".join(f"{k}={v}" for k, v in selector.items())
                    doc_parts.append(f"Selector: {sel_str}")
                    # Link to deployments matching selector
                    for dep_name, dep_labels in deployments_by_labels:
                        if all(
                            dep_labels.get(k) == str(v) for k, v in selector.items()
                        ):
                            calls.append(dep_name)

            elif kind in ("Deployment", "StatefulSet", "DaemonSet"):
                replicas = spec.get("replicas", 1)
                template = spec.get("template", {}) or {}
                t_spec = template.get("spec", {}) or {}
                containers = t_spec.get("containers", []) or []

                container_descs: list[str] = []
                for c in containers:
                    if not isinstance(c, dict):
                        continue
                    c_name = c.get("name", "app")
                    c_img = c.get("image", "unknown")
                    container_descs.append(f"{c_name} ({c_img})")

                    # Environment variables in container
                    for env_item in c.get("env", []) or []:
                        if isinstance(env_item, dict) and "name" in env_item:
                            var_name = env_item["name"]
                            calls.append(var_name)
                            # ConfigMap or Secret reference
                            val_from = env_item.get("valueFrom", {}) or {}
                            if "configMapKeyRef" in val_from:
                                calls.append(
                                    val_from["configMapKeyRef"].get("name", "")
                                )
                            if "secretKeyRef" in val_from:
                                calls.append(val_from["secretKeyRef"].get("name", ""))

                    # envFrom
                    for ef in c.get("envFrom", []) or []:
                        if isinstance(ef, dict):
                            if "configMapRef" in ef:
                                calls.append(ef["configMapRef"].get("name", ""))
                            if "secretRef" in ef:
                                calls.append(ef["secretRef"].get("name", ""))

                # Volumes (PVCs)
                for vol in t_spec.get("volumes", []) or []:
                    if isinstance(vol, dict) and "persistentVolumeClaim" in vol:
                        claim_name = vol["persistentVolumeClaim"].get("claimName", "")
                        if claim_name:
                            calls.append(claim_name)

                signature = f"{kind} {name} (replicas: {replicas}, containers: {', '.join(container_descs)})"

            elif kind == "NetworkPolicy":
                pod_selector = spec.get("podSelector", {}).get("matchLabels", {}) or {}
                doc_parts.append(f"PodSelector: {pod_selector}")

                # Target pods matching policy
                for dep_name, dep_labels in deployments_by_labels:
                    if all(
                        dep_labels.get(k) == str(v) for k, v in pod_selector.items()
                    ):
                        calls.append(dep_name)

                # Ingress rules
                for ing in spec.get("ingress", []) or []:
                    if not isinstance(ing, dict):
                        continue
                    for from_rule in ing.get("from", []) or []:
                        if isinstance(from_rule, dict) and "podSelector" in from_rule:
                            from_labels = (
                                from_rule["podSelector"].get("matchLabels", {}) or {}
                            )
                            for dep_name, dep_labels in deployments_by_labels:
                                if all(
                                    dep_labels.get(k) == str(v)
                                    for k, v in from_labels.items()
                                ):
                                    calls.append(dep_name)

            elif kind == "ConfigMap":
                data = doc.get("data", {}) or {}
                keys = list(data.keys()) if isinstance(data, dict) else []
                signature = f"ConfigMap {name} (keys: {', '.join(keys[:8])})"
                calls.extend(keys)

            elif kind == "Secret":
                data = doc.get("data", {}) or doc.get("stringData", {}) or {}
                keys = list(data.keys()) if isinstance(data, dict) else []
                sec_type = doc.get("type", "Opaque")
                signature = (
                    f"Secret {name} (type: {sec_type}, keys: {', '.join(keys[:8])})"
                )
                calls.extend(keys)

            elif kind == "PersistentVolumeClaim":
                resources = spec.get("resources", {}).get("requests", {}) or {}
                storage = resources.get("storage", "unspecified")
                access_modes = spec.get("accessModes", [])
                signature = f"PersistentVolumeClaim {name} (storage: {storage}, modes: {', '.join(access_modes)})"

            elif kind == "Ingress":
                rules = spec.get("rules", []) or []
                hosts: list[str] = []
                for r in rules:
                    if isinstance(r, dict):
                        hosts.append(r.get("host", "*"))
                        http_paths = r.get("http", {}).get("paths", []) or []
                        for p in http_paths:
                            backend = p.get("backend", {}) or {}
                            svc_name = backend.get("service", {}).get(
                                "name", ""
                            ) or backend.get("serviceName", "")
                            if svc_name:
                                calls.append(svc_name)
                signature = f"Ingress {name} (hosts: {', '.join(hosts)})"

            # Clean and deduplicate calls
            clean_calls = [c for c in sorted(set(calls)) if c and c != name]

            # Extract snippet of the resource
            lines = content.splitlines()[start_line - 1 : end_line]
            snippet = "\n".join(lines[:20])

            unit = DeclarationUnit(
                name=name,
                kind=unit_kind,
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                signature=signature,
                docstring=" | ".join(doc_parts),
                calls=clean_calls,
                body_snippet=snippet,
            )
            units.append(unit)

        return units

    @classmethod
    def _find_document_line_spans(cls, content: str) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        lines = content.splitlines()
        start = 1
        for idx, line in enumerate(lines, 1):
            if line.strip() == "---" and idx > start:
                spans.append((start, idx - 1))
                start = idx + 1
        if start <= len(lines):
            spans.append((start, len(lines)))
        return spans
