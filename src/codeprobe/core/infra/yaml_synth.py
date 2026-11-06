from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class StructuralYamlSynthesizer:
    """
    Zero-dependency indentation-aware YAML block synthesizer for Kubernetes manifests
    and Kustomization files. Preserves all comments, blank lines, and original formatting.
    """

    @classmethod
    def is_k8s_manifest(cls, content: str) -> bool:
        """Determines if YAML content is a Kubernetes resource."""
        return "apiVersion:" in content and "kind:" in content

    @classmethod
    def is_kustomization(cls, file_path: str, content: str) -> bool:
        """Determines if file is a Kustomize configuration."""
        name = Path(file_path).name.lower()
        if "kustomiz" in name:
            return True
        return "resources:" in content or "configMapGenerator:" in content

    @classmethod
    def synthesize_k8s_env_target(
        cls,
        file_path: str,
        content: str,
        env_var_name: str = "CONFIG_PARAM",
        secret_name: str = "app-secrets",
    ) -> tuple[int, int, str, str] | None:
        """
        Locates the primary container specification in a Kubernetes manifest (CronJob,
        Deployment, StatefulSet, DaemonSet, Pod) and generates an anchor with exact
        hierarchical indentation for adding an environment variable.

        Returns (start_line, end_line, target_content, replacement_content) or None.
        """
        lines = content.splitlines(keepends=True)
        if not lines:
            return None

        # Look for containers list
        containers_idx = -1
        containers_indent = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("containers:"):
                containers_idx = i
                containers_indent = len(line) - len(line.lstrip(" "))
                break

        if containers_idx == -1:
            return None

        # Find first container item (- name: ...) after containers:
        first_container_idx = -1
        item_indent = containers_indent + 2
        for i in range(containers_idx + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            current_indent = len(line) - len(line.lstrip(" "))
            if (
                current_indent <= containers_indent
                and stripped
                and not stripped.startswith("#")
            ):
                break
            if stripped.startswith("- name:"):
                first_container_idx = i
                item_indent = current_indent
                break

        if first_container_idx == -1:
            return None

        # Check if this container already has an 'env:' block
        env_block_idx = -1
        env_indent = item_indent + 2
        env_last_item_idx = -1

        for i in range(first_container_idx + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            current_indent = len(line) - len(line.lstrip(" "))

            # If we exited the container block (same or lower indent than container item)
            if (
                current_indent <= item_indent
                and stripped
                and not stripped.startswith("#")
            ):
                break

            if stripped.startswith("env:"):
                env_block_idx = i
                env_indent = current_indent
                # Continue searching for the last item in this env: block
                for j in range(i + 1, len(lines)):
                    j_line = lines[j]
                    j_stripped = j_line.strip()
                    j_indent = len(j_line) - len(j_line.lstrip(" "))

                    if (
                        j_indent <= env_indent
                        and j_stripped
                        and not j_stripped.startswith("#")
                    ):
                        break
                    if j_stripped.startswith("- name:"):
                        env_last_item_idx = j
                break

        # Case 1: Existing env: block found
        if env_block_idx != -1:
            anchor_idx = env_last_item_idx if env_last_item_idx != -1 else env_block_idx
            # Find end of the item at anchor_idx
            end_item_idx = anchor_idx
            for k in range(anchor_idx + 1, len(lines)):
                k_line = lines[k]
                k_stripped = k_line.strip()
                k_indent = len(k_line) - len(k_line.lstrip(" "))
                if (
                    k_indent <= (env_indent + 2)
                    and k_stripped
                    and not k_stripped.startswith("#")
                ):
                    break
                end_item_idx = k

            target_slice = lines[anchor_idx : end_item_idx + 1]
            target_content = "".join(target_slice)
            start_line = anchor_idx + 1
            end_line = end_item_idx + 1

            pad = " " * (env_indent + 2)
            sub_pad = " " * (env_indent + 4)
            new_entry = (
                f"{pad}- name: {env_var_name}\n"
                f"{sub_pad}valueFrom:\n"
                f"{sub_pad}  secretKeyRef:\n"
                f"{sub_pad}    name: {secret_name}\n"
                f"{sub_pad}    key: {env_var_name}\n"
            )
            replacement_content = target_content + new_entry
            return start_line, end_line, target_content, replacement_content

        # Case 2: No env: block in this container -> Anchor right after container - name: line
        target_slice = lines[first_container_idx : first_container_idx + 1]
        target_content = "".join(target_slice)
        start_line = first_container_idx + 1
        end_line = first_container_idx + 1

        env_header_pad = " " * (item_indent + 2)
        pad = " " * (item_indent + 4)
        sub_pad = " " * (item_indent + 6)
        new_block = (
            f"{env_header_pad}env:\n"
            f"{pad}- name: {env_var_name}\n"
            f"{sub_pad}valueFrom:\n"
            f"{sub_pad}  secretKeyRef:\n"
            f"{sub_pad}    name: {secret_name}\n"
            f"{sub_pad}    key: {env_var_name}\n"
        )
        replacement_content = target_content + new_block
        return start_line, end_line, target_content, replacement_content

    @classmethod
    def synthesize_kustomize_resource_target(
        cls,
        file_path: str,
        content: str,
        resource_path: str = "scripts/backup.sh",
    ) -> tuple[int, int, str, str] | None:
        """
        Locates the 'resources:' or 'configMapGenerator:' block in a Kustomization
        manifest and cleanly appends the given resource with exact indentation.
        """
        lines = content.splitlines(keepends=True)
        if not lines:
            return None

        # Look for resources: or configMapGenerator:
        key_idx = -1
        key_indent = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("resources:", "configMapGenerator:")):
                key_idx = i
                key_indent = len(line) - len(line.lstrip(" "))
                break

        if key_idx == -1:
            # Fallback: anchor at end of file
            target_content = lines[-1] if lines else "\n"
            start_line = len(lines) if lines else 1
            end_line = start_line
            replacement_content = (
                target_content + f"\nresources:\n  - {resource_path}\n"
            )
            return start_line, end_line, target_content, replacement_content

        # Find the last item under this block
        last_item_idx = key_idx
        item_indent = key_indent + 2

        for i in range(key_idx + 1, len(lines)):
            line = lines[i]
            stripped = line.strip()
            current_indent = len(line) - len(line.lstrip(" "))

            if (
                current_indent <= key_indent
                and stripped
                and not stripped.startswith("#")
            ):
                break
            if stripped.startswith("-"):
                last_item_idx = i
                item_indent = current_indent

        target_slice = lines[last_item_idx : last_item_idx + 1]
        target_content = "".join(target_slice)
        start_line = last_item_idx + 1
        end_line = last_item_idx + 1

        pad = " " * item_indent
        new_entry = f"{pad}- {resource_path}\n"
        replacement_content = target_content + new_entry
        return start_line, end_line, target_content, replacement_content
