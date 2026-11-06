from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from ...schemas import DeclarationUnit

logger = logging.getLogger(__name__)


class DockerComposeParser:
    """
    Parses docker-compose.yml / compose.yaml into DeclarationUnits,
    mapping services, dependencies (depends_on), exposed ports, environment variables,
    and volume configurations.
    """

    @classmethod
    def is_compose_file(cls, file_path: str) -> bool:
        name = Path(file_path).name.lower()
        return name in (
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        )

    @classmethod
    def parse(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        try:
            data = yaml.safe_load(content)
        except (yaml.YAMLError, OSError) as exc:
            logger.debug(
                "Failed to parse Docker Compose YAML in %s: %s", file_path, exc
            )
            return []

        if not isinstance(data, dict):
            return []

        services = data.get("services", {})
        if not isinstance(services, dict):
            return []

        units: list[DeclarationUnit] = []
        lines = content.splitlines()

        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue

            image = svc_cfg.get("image", svc_cfg.get("build", "custom_build"))
            if isinstance(image, dict):
                image = image.get("context", "custom_build")

            container_name = svc_cfg.get("container_name", "")
            ports_raw = svc_cfg.get("ports", []) or []
            ports: list[str] = []
            for p in ports_raw:
                ports.append(str(p))

            depends_on_raw = svc_cfg.get("depends_on", []) or []
            depends_on: list[str] = []
            if isinstance(depends_on_raw, list):
                depends_on = [str(d) for d in depends_on_raw]
            elif isinstance(depends_on_raw, dict):
                depends_on = [str(k) for k in depends_on_raw]

            # Environment variables
            env_vars: list[str] = []
            env_raw = svc_cfg.get("environment", []) or []
            if isinstance(env_raw, list):
                for item in env_raw:
                    if "=" in str(item):
                        env_vars.append(str(item).split("=", 1)[0].strip())
                    else:
                        env_vars.append(str(item).strip())
            elif isinstance(env_raw, dict):
                env_vars.extend(str(k).strip() for k in env_raw)

            # Env files
            env_files_raw = svc_cfg.get("env_file", []) or []
            env_files: list[str] = []
            if isinstance(env_files_raw, list):
                env_files = [str(ef) for ef in env_files_raw]
            elif isinstance(env_files_raw, str):
                env_files = [env_files_raw]

            # Volumes
            volumes_raw = svc_cfg.get("volumes", []) or []
            volume_targets: list[str] = []
            for v in volumes_raw:
                if isinstance(v, str) and ":" in v:
                    volume_targets.append(v.split(":")[0])
                elif isinstance(v, dict) and "source" in v:
                    volume_targets.append(str(v["source"]))

            # Find approximate line span
            start_line, end_line = cls._find_service_line_span(lines, svc_name)
            snippet = "\n".join(lines[start_line - 1 : end_line][:20])

            calls = sorted(set(depends_on + env_vars + env_files + volume_targets))
            clean_calls = [c for c in calls if c and c != svc_name]

            doc_parts = [f"Service: {svc_name}", f"Image: {image}"]
            if container_name:
                doc_parts.append(f"Container: {container_name}")
            if ports:
                doc_parts.append(f"Ports: {', '.join(ports)}")
            if depends_on:
                doc_parts.append(f"DependsOn: {', '.join(depends_on)}")
            if env_vars:
                doc_parts.append(f"EnvVars: {', '.join(env_vars[:8])}")

            sig = f"DockerService {svc_name} (image: {image}"
            if ports:
                sig += f", ports: {', '.join(ports)}"
            sig += ")"

            units.append(
                DeclarationUnit(
                    name=svc_name,
                    kind="docker_service",
                    file_path=file_path,
                    start_line=start_line,
                    end_line=end_line,
                    signature=sig,
                    docstring=" | ".join(doc_parts),
                    calls=clean_calls,
                    body_snippet=snippet,
                )
            )

        return units

    @classmethod
    def _find_service_line_span(
        cls, lines: list[str], svc_name: str
    ) -> tuple[int, int]:
        pattern = re.compile(rf"^\s*{re.escape(svc_name)}:\s*$")
        start = 1
        found = False
        for i, line in enumerate(lines, 1):
            if pattern.match(line):
                start = i
                found = True
                break

        if not found:
            return 1, min(len(lines), 30)

        # Find where next service starts at same indentation
        indent = len(lines[start - 1]) - len(lines[start - 1].lstrip())
        end = len(lines)
        for i in range(start, len(lines)):
            line = lines[i]
            if line.strip() and not line.strip().startswith("#"):
                line_indent = len(line) - len(line.lstrip())
                if line_indent <= indent:
                    end = i
                    break
        return start, end


class DockerfileParser:
    """
    Parses Dockerfiles into DeclarationUnits, extracting base images (FROM),
    exposed ports (EXPOSE), environment variables (ENV), and command entrypoints.
    """

    @classmethod
    def is_dockerfile(cls, file_path: str) -> bool:
        name = Path(file_path).name.lower()
        return name == "dockerfile" or name.startswith("dockerfile.")

    @classmethod
    def parse(cls, content: str, file_path: str = "") -> list[DeclarationUnit]:
        lines = content.splitlines()
        if not lines:
            return []

        base_images: list[str] = []
        exposed_ports: list[str] = []
        env_vars: list[str] = []
        entrypoints: list[str] = []

        for line in lines:
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue

            # FROM <image> [AS <stage>]
            m_from = re.match(r"(?i)^FROM\s+([^\s]+)", clean)
            if m_from:
                base_images.append(m_from.group(1))

            # EXPOSE <port>
            m_expose = re.match(r"(?i)^EXPOSE\s+([0-9a-zA-Z\/\s]+)", clean)
            if m_expose:
                for p in m_expose.group(1).split():
                    exposed_ports.append(p.strip())

            # ENV <key>=<val> or ENV <key> <val>
            m_env = re.match(
                r"(?i)^ENV\s+([A-Za-z_][A-Za-z0-9_]*)(?:=|\s+)(.*)$", clean
            )
            if m_env:
                env_vars.append(m_env.group(1).strip())

            # ENTRYPOINT / CMD
            m_entry = re.match(r"(?i)^(?:ENTRYPOINT|CMD)\s+(.*)$", clean)
            if m_entry:
                entrypoints.append(m_entry.group(1).strip())

        file_name = Path(file_path).name if file_path else "Dockerfile"
        name = file_name
        sig = f"Dockerfile {file_name}"
        if base_images:
            sig += f" (FROM {', '.join(base_images)})"

        doc_parts = [f"BaseImages: {', '.join(base_images)}"]
        if exposed_ports:
            doc_parts.append(f"ExposedPorts: {', '.join(exposed_ports)}")
        if env_vars:
            doc_parts.append(f"EnvVars: {', '.join(env_vars[:8])}")
        if entrypoints:
            doc_parts.append(f"Entrypoint: {entrypoints[0][:60]}")

        calls = sorted(set(base_images + exposed_ports + env_vars))

        return [
            DeclarationUnit(
                name=name,
                kind="dockerfile",
                file_path=file_path,
                start_line=1,
                end_line=len(lines),
                signature=sig,
                docstring=" | ".join(doc_parts),
                calls=calls,
                body_snippet="\n".join(lines[:25]),
            )
        ]
