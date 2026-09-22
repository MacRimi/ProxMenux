from __future__ import annotations

import json
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .casaos import (
    canonical_image_repository,
    convert_casaos_compose,
    image_provider,
    image_repository_url,
    normalize_app_id,
    summarize_casaos_compose,
)
from .converter import ConversionError, convert_readme, summarize_readme
from .github_source import GitHubSource, Repository, SourceError

SUPPORTED_CATALOG_ARCHITECTURES = ("amd64", "arm64")
# Size of a container volume the installation does not ask about: its size is
# not the user's decision, so it is given room to grow.
MINIMUM_VOLUME_GB = 16


def supported_architectures(values: list[str]) -> list[str]:
    return [architecture for architecture in SUPPORTED_CATALOG_ARCHITECTURES if architecture in values]


def imported_catalog_id(summary: dict[str, Any], used_ids: set[str]) -> str:
    if summary.get("variant"):
        candidate = f"{summary['base_id']}-{summary['variant']}"
    elif summary["base_id"] in used_ids:
        candidate = f"{summary['base_id']}-{summary['distribution']}"
    else:
        candidate = summary["id"]
    if candidate in used_ids:
        candidate = f"{candidate}-{summary['distribution']}"
    base_candidate = candidate
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base_candidate}-{suffix}"
        suffix += 1
    return candidate


MULTI_CONTAINER_TEMPLATES = {"image-immich", "image-nextcloud-stack", "image-paperless-ngx", "image-tandoor"}


def is_multi_container(template: dict[str, Any]) -> bool:
    driver = template.get("proxmox", {}).get("installer_profile", {}).get("stack_driver")
    return template.get("id") in MULTI_CONTAINER_TEMPLATES or driver in ("generic-multi-lxc-stack", "arr-suite")


class Catalog:
    def __init__(self, root: Path, source: GitHubSource | None = None) -> None:
        self.root = root
        self.catalog_dir = root / "catalog"
        self.apps_dir = self.catalog_dir / "apps"
        self.curated_dir = self.catalog_dir / "curated"
        self.overlays_dir = self.catalog_dir / "overlays"
        self.exclusions_path = self.catalog_dir / "exclusions.json"
        self.categories_path = self.catalog_dir / "categories.json"
        self._categories: dict[str, Any] | None = None
        self.volume_policy_path = self.catalog_dir / "volume-policy.json"
        self._volume_policy: dict[str, Any] | None = None
        self.index_path = self.catalog_dir / "index.json"
        self.schema_path = root / "schemas" / "oci-template.schema.json"
        self.source = source or GitHubSource()

    def sync_index(self) -> dict[str, Any]:
        repos = self.source.list_linuxserver_repositories()
        try:
            proxmenux_metadata = self.source.proxmenux_app_metadata()
        except (AttributeError, SourceError, OSError, RuntimeError):
            proxmenux_metadata = {}
        existing = self._existing_template_statuses()
        discovered: list[tuple[Repository, dict[str, Any]]] = []
        linuxserver_skipped: list[dict[str, str]] = []

        def inspect(repo: Repository) -> tuple[Repository, dict[str, Any]]:
            readme = self.source.readme_at_branch(repo)
            return repo, summarize_readme(repo, readme)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(inspect, repo): repo for repo in repos}
            for future in as_completed(futures):
                repo = futures[future]
                try:
                    discovered.append(future.result())
                except (ConversionError, OSError, RuntimeError) as exc:
                    linuxserver_skipped.append({"repository": repo.name, "reason": str(exc)})
        discovered.sort(key=lambda item: item[0].app_id.casefold())
        linuxserver_items = [
            {
                "id": repo.app_id,
                "provider": "linuxserver.io",
                "title": summary["title"],
                "repository_name": repo.name,
                "repository": repo.html_url,
                "description": summary["description"],
                "website": summary["website"],
                "icon": summary["icon"],
                "architectures": supported_architectures(summary["architectures"]),
                "default_branch": repo.default_branch,
                "pushed_at": repo.pushed_at,
                "updated_at": summary["updated_at"],
                "main_image": summary["main_image"],
                "category": proxmenux_metadata.get(repo.app_id, {}).get("category", "misc"),
                "category_label": proxmenux_metadata.get(repo.app_id, {}).get(
                    "category_label", "Miscellaneous"
                ),
                "template": f"apps/{repo.app_id}.json" if repo.app_id in existing else None,
                "template_status": existing.get(repo.app_id),
                "content_hash": self._template_hash(repo.app_id) if repo.app_id in existing else None,
            }
            for repo, summary in discovered
        ]

        curated_items = self._curated_items(existing)

        casaos_state = self.source.casaos_state()
        casaos_discovered: list[tuple[str, dict[str, Any]]] = []
        casaos_skipped: list[dict[str, str]] = []

        def inspect_casaos(path: str) -> tuple[str, dict[str, Any]]:
            compose_text, _ = self.source.casaos_compose(path, casaos_state["revision"])
            return path, summarize_casaos_compose(compose_text, path)

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(inspect_casaos, path): path for path in casaos_state["paths"]}
            for future in as_completed(futures):
                path = futures[future]
                try:
                    casaos_discovered.append(future.result())
                except (ConversionError, OSError, RuntimeError) as exc:
                    casaos_skipped.append({"path": path, "reason": str(exc)})
        casaos_discovered.sort(key=lambda item: item[1]["id"])
        imported_exclusions = self._imported_exclusions()
        excluded_imports: list[dict[str, str]] = []

        linuxserver_images = {
            canonical_image_repository(item["main_image"]): item["id"] for item in linuxserver_items
        }
        duplicates: list[dict[str, Any]] = []
        casaos_items: list[dict[str, Any]] = []
        used_ids = {item["id"] for item in linuxserver_items + curated_items}
        curated_replacements = {
            source_id: item["id"]
            for item in curated_items
            for source_id in item.get("replaces_discovered_ids", [])
        }
        for path, summary in casaos_discovered:
            if summary["id"] in imported_exclusions:
                excluded_imports.append(
                    {
                        "source_id": summary["id"],
                        "source_path": path,
                        "reason": imported_exclusions[summary["id"]],
                    }
                )
                continue
            replaced_by = curated_replacements.get(summary["id"])
            if replaced_by:
                duplicates.append(
                    {
                        "source_id": summary["id"],
                        "source_path": path,
                        "main_image": summary["main_image"],
                        "matched_catalog_id": replaced_by,
                        "reason": "replaced-by-curated-laboratory-profile",
                    }
                )
                continue
            matched_linuxserver = linuxserver_images.get(summary["main_image_repository"])
            if matched_linuxserver and summary["variant"] is None:
                duplicates.append(
                    {
                        "source_id": summary["id"],
                        "source_path": path,
                        "main_image": summary["main_image"],
                        "matched_catalog_id": matched_linuxserver,
                        "reason": "same-linuxserver-image-without-distinct-deployment-variant",
                    }
                )
                continue
            catalog_id = imported_catalog_id(summary, used_ids)
            used_ids.add(catalog_id)
            metadata = proxmenux_metadata.get(summary["id"], {})
            if not metadata.get("category") and catalog_id in existing:
                # The upstream metadata is keyed by the source application id
                # and does not always carry a category, while the generated
                # template has already resolved one. Without this the entry
                # reaches the index under no category at all and the reader
                # cannot find it by browsing.
                try:
                    generated_ui = json.loads(
                        (self.apps_dir / f"{catalog_id}.json").read_text(encoding="utf-8")
                    )["catalog_ui"]
                    metadata = {
                        **metadata,
                        "category": generated_ui.get("category"),
                        "category_label": generated_ui.get("category_label"),
                    }
                except (OSError, ValueError, KeyError):
                    pass
            casaos_items.append(
                {
                    "id": catalog_id,
                    "source_app_id": summary["id"],
                    "provider": image_provider(summary["distribution"]),
                    "template_family": "imported-compose",
                    "variant": summary["variant"],
                    "title": summary["title"],
                    "repository": image_repository_url(summary["main_image"]),
                    "description": summary["description"],
                    "website": summary["website"],
                    "icon": summary["icon"],
                    "architectures": supported_architectures(summary["architectures"]),
                    "default_branch": "main",
                    "source_path": path,
                    "source_revision": casaos_state["revision"],
                    "pushed_at": casaos_state["pushed_at"],
                    "updated_at": summary["updated_at"],
                    "main_image": summary["selected_image"],
                    "category": metadata.get("category"),
                    "category_label": metadata.get("category_label"),
                    "template": f"apps/{catalog_id}.json" if catalog_id in existing else None,
                    "template_status": existing.get(catalog_id),
                    "content_hash": self._template_hash(catalog_id) if catalog_id in existing else None,
                }
            )

        applications = sorted(
            linuxserver_items + curated_items + casaos_items,
            key=lambda item: item["id"].casefold(),
        )
        payload = {
            "schema_version": "0.2.0",
            "kind": "proxmenux.oci-catalog-index",
            "provider": "multiple-container-images",
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "applications": applications,
            "discovery": {
                "linuxserver": {
                    "repositories_examined": len(repos),
                    "compose_applications": len(discovered),
                    "skipped_count": len(linuxserver_skipped),
                    "skipped": sorted(linuxserver_skipped, key=lambda item: item["repository"]),
                },
                "imported_composes": {
                    "compose_applications": len(casaos_discovered),
                    "included_count": len(casaos_items),
                    "duplicate_count": len(duplicates),
                    "duplicates": duplicates,
                    "excluded_count": len(excluded_imports),
                    "excluded": excluded_imports,
                    "skipped_count": len(casaos_skipped),
                    "skipped": sorted(casaos_skipped, key=lambda item: item["path"]),
                },
                "curated_profiles": {"included_count": len(curated_items)},
            },
        }
        self._enrich_index_from_templates(payload)
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.index_path, payload)
        return payload

    def _imported_exclusions(self) -> dict[str, str]:
        if not self.exclusions_path.exists():
            return {}
        payload = json.loads(self.exclusions_path.read_text(encoding="utf-8"))
        return {
            str(item["id"]): str(item["reason"])
            for item in payload.get("imported_applications", [])
        }

    def load_index(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return self.sync_index()
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        self._enrich_index_from_templates(payload)
        return payload

    def categories(self) -> dict[str, Any]:
        """Category labels and the per-application corrections of categories.json."""
        if self._categories is None:
            try:
                data = json.loads(self.categories_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            self._categories = {"labels": data.get("labels", {}), "applications": data.get("applications", {})}
        return self._categories

    def _apply_category(self, app_id: str, ui: dict[str, Any]) -> None:
        data = self.categories()
        key = data["applications"].get(app_id) or ui.get("category") or "misc"
        ui["category"] = key
        ui["category_label"] = data["labels"].get(key) or ui.get("category_label") or key

    def volume_policy(self) -> dict[str, Any]:
        """Paths of volume-policy.json that hold content of the user."""
        if self._volume_policy is None:
            try:
                data = json.loads(self.volume_policy_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            self._volume_policy = {"shared_paths": set(data.get("shared_paths", [])),
                                   "applications": data.get("applications", {})}
        return self._volume_policy

    def _apply_volume_policy(self, app_id: str, contract: dict[str, Any]) -> None:
        """A path that holds content of the user is offered as a container
        volume or as a host directory, and the installation asks which one; the
        state of the application stays in a container volume without asking."""
        policy = self.volume_policy()
        shared = policy["shared_paths"] | set(policy["applications"].get(app_id, []))
        for volume in contract.get("volumes", []):
            choices = volume.get("installation_choice", [])
            if "managed-volume" not in choices:
                continue
            optional = "skip" in choices
            if volume["container_path"] in shared or volume.get("default") == "host-bind":
                volume["installation_choice"] = ["managed-volume", "host-bind"] + (["skip"] if optional else [])
                continue
            volume["installation_choice"] = ["managed-volume"] + (["skip"] if optional else [])
            if volume.get("default") not in volume["installation_choice"]:
                volume["default"] = "managed-volume"
            managed = volume.get("managed_volume")
            if isinstance(managed, dict):
                managed["default_size_gb"] = max(int(managed.get("default_size_gb") or 0), MINIMUM_VOLUME_GB)

    def _enrich_index_from_templates(self, payload: dict[str, Any]) -> None:
        for item in payload.get("applications", []):
            overlay_path = self.overlays_dir / f"{item['id']}.json"
            overlay_ui = json.loads(overlay_path.read_text(encoding="utf-8")).get("catalog_ui", {}) if overlay_path.exists() else {}
            item["hidden"] = overlay_ui.get("hidden", False)
            path = self.apps_dir / f"{item['id']}.json"
            if not path.exists():
                item["architectures"] = supported_architectures(
                    item.get("architectures", [])
                )
                continue
            try:
                template = json.loads(path.read_text(encoding="utf-8"))
                compatibility = template["compatibility"]
                ui = template["catalog_ui"]
                item["hidden"] = overlay_ui.get("hidden", ui.get("hidden", False))
                item["template_status"] = template["status"]
                item["automatic_install_candidate"] = compatibility[
                    "automatic_install_candidate"
                ]
                item["untranslated_blockers"] = compatibility[
                    "untranslated_blockers"
                ]
                item["requires_privileged_lxc"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("requires_privileged_lxc")
                )
                item["optional_privileged_lxc"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("optional_privileged_lxc")
                )
                item["requires_host_pid_namespace"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("requires_host_pid_namespace")
                )
                item["requires_relaxed_confinement"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("requires_relaxed_confinement")
                )
                item["optional_relaxed_confinement"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("optional_relaxed_confinement")
                )
                item["requires_security_confirmation"] = bool(
                    template.get("proxmox", {})
                    .get("security_profile", {})
                    .get("confirmation_required")
                )
                item["architectures"] = supported_architectures(
                    overlay_ui.get("architectures", ui["architectures"]))
                self._apply_category(item["id"], ui)
                item["category"] = ui["category"]
                item["category_label"] = ui["category_label"]
                item["multi_container"] = is_multi_container(template)
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                item["automatic_install_candidate"] = False
                item["untranslated_blockers"] = ["invalid-generated-template"]

    def find_repo(self, app_id: str) -> Repository:
        item = self.find_item(app_id)
        if item.get("provider", "linuxserver.io") == "linuxserver.io":
                metadata = {
                    "category": item.get("category"),
                    "category_label": item.get("category_label"),
                }
                if not metadata["category"]:
                    try:
                        metadata.update(self.source.proxmenux_app_metadata().get(app_id, {}))
                    except (AttributeError, SourceError, OSError, RuntimeError):
                        pass
                return self._repository_from_item(item, metadata)
        raise ConversionError(f"The application '{app_id}' does not come from LinuxServer")

    def find_item(self, app_id: str) -> dict[str, Any]:
        folded = app_id.casefold()
        for item in self.load_index()["applications"]:
            if item["id"].casefold() == folded:
                return item
        raise ConversionError(f"The application '{app_id}' is not in the index")

    @staticmethod
    def _repository_from_item(
        item: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> Repository:
        metadata = metadata or {}
        return Repository(
            name=item["repository_name"],
            description=item.get("description") or "",
            default_branch=item.get("default_branch") or "master",
            html_url=item["repository"],
            pushed_at=item.get("pushed_at") or "",
            category=metadata.get("category") or item.get("category") or "misc",
            category_label=metadata.get("category_label") or item.get("category_label") or "Miscellaneous",
        )

    def _preserve_registry_state(self, app_id: str, template: dict[str, Any]) -> None:
        existing_path = self.apps_dir / f"{app_id}.json"
        if not existing_path.exists():
            return
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
            state = existing.get("lifecycle", {}).get("registry_state", {})
            if not state.get("resolved_digest"):
                return
            template["lifecycle"]["registry_state"] = state
            template["catalog_ui"]["display_version"] = existing.get("catalog_ui", {}).get("display_version")
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            return

    def generate(self, app_id: str) -> tuple[Path, dict[str, Any]]:
        item = self.find_item(app_id)
        provider = item.get("provider", "linuxserver.io")
        if item.get("template_family", "linuxserver-readme") == "linuxserver-readme":
            repo = self._repository_from_item(item)
            readme, revision, raw_url = self.source.readme(repo)
            template = convert_readme(repo, readme, revision, raw_url)
        elif item.get("template_family") == "imported-compose":
            revision = item["source_revision"]
            compose, raw_url = self.source.casaos_compose(item["source_path"], revision)
            template = convert_casaos_compose(
                compose,
                revision,
                raw_url,
                item["source_path"],
                item.get("pushed_at") or "",
                item.get("category"),
                item.get("category_label"),
                item["id"],
            )
        elif item.get("template_family") == "curated-profile":
            template = json.loads((self.root / item["curated_path"]).read_text(encoding="utf-8"))
        else:
            raise ConversionError(f"Proveedor no soportado: {provider}")
        catalog_id = item["id"]
        self._apply_overlay(catalog_id, template)
        self._preserve_registry_state(catalog_id, template)
        self.validate(template)
        self.apps_dir.mkdir(parents=True, exist_ok=True)
        destination = self.apps_dir / f"{catalog_id}.json"
        self._write_json(destination, template)
        self._update_index_template(catalog_id, template["status"])
        return destination, template

    def generate_all(self, progress: Any | None = None, provider: str = "all") -> dict[str, Any]:
        index = self.load_index()
        applications = [
            item
            for item in index["applications"]
            if provider == "all"
            or (provider == "imported" and item.get("template_family") == "imported-compose")
            or (provider == "curated" and item.get("template_family") == "curated-profile")
            or item.get("provider", "linuxserver.io") == provider
        ]
        if any(item.get("template_family", "linuxserver-readme") == "linuxserver-readme" for item in applications) and not self.source.token:
            raise ConversionError(
                "Bulk generation requires GITHUB_TOKEN to obtain an immutable revision per application"
            )
        generated: list[str] = []
        failed: list[dict[str, str]] = []
        templates: dict[str, dict[str, Any]] = {}

        def convert(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            item_provider = item.get("provider", "linuxserver.io")
            if item.get("template_family", "linuxserver-readme") == "linuxserver-readme":
                repo = self._repository_from_item(item)
                readme, revision, raw_url = self.source.readme(repo)
                template = convert_readme(repo, readme, revision, raw_url)
            elif item.get("template_family") == "imported-compose":
                revision = item["source_revision"]
                compose, raw_url = self.source.casaos_compose(item["source_path"], revision)
                template = convert_casaos_compose(
                    compose,
                    revision,
                    raw_url,
                    item["source_path"],
                    item.get("pushed_at") or "",
                    item.get("category"),
                    item.get("category_label"),
                    item["id"],
                )
            elif item.get("template_family") == "curated-profile":
                template = json.loads(
                    (self.root / item["curated_path"]).read_text(encoding="utf-8")
                )
            else:
                raise ConversionError(f"Proveedor no soportado: {item_provider}")
            self._apply_overlay(item["id"], template)
            self._preserve_registry_state(item["id"], template)
            self.validate(template)
            return item["id"], template

        completed = 0
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(convert, item): item for item in applications}
            for future in as_completed(futures):
                item = futures[future]
                completed += 1
                try:
                    app_id, template = future.result()
                    templates[app_id] = template
                    generated.append(app_id)
                    outcome = "ok"
                except (ConversionError, OSError, RuntimeError) as exc:
                    failed.append({"id": item["id"], "reason": str(exc)})
                    outcome = "error"
                if progress:
                    progress(completed, len(applications), item["id"], outcome)

        self.apps_dir.mkdir(parents=True, exist_ok=True)
        index_items = {item["id"]: item for item in applications}
        for app_id in sorted(templates):
            template = templates[app_id]
            self._write_json(self.apps_dir / f"{app_id}.json", template)
            item = index_items[app_id]
            item["template"] = f"apps/{app_id}.json"
            item["template_status"] = template["status"]
            item["automatic_install_candidate"] = template["compatibility"][
                "automatic_install_candidate"
            ]
            item["untranslated_blockers"] = template["compatibility"][
                "untranslated_blockers"
            ]
            item["requires_privileged_lxc"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("requires_privileged_lxc")
            )
            item["optional_privileged_lxc"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("optional_privileged_lxc")
            )
            item["requires_host_pid_namespace"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("requires_host_pid_namespace")
            )
            item["requires_relaxed_confinement"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("requires_relaxed_confinement")
            )
            item["optional_relaxed_confinement"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("optional_relaxed_confinement")
            )
            item["requires_security_confirmation"] = bool(
                template.get("proxmox", {})
                .get("security_profile", {})
                .get("confirmation_required")
            )
            item["architectures"] = supported_architectures(
                template["catalog_ui"]["architectures"]
            )
            item["content_hash"] = self._template_hash(app_id)
        self._write_json(self.index_path, index)
        generated.sort()
        failed.sort(key=lambda item: item["id"])
        report = {
            "generated": generated,
            "generated_count": len(generated),
            "failed": failed,
            "failed_count": len(failed),
        }
        report_name = "generation-report.json" if provider == "all" else f"generation-report-{provider}.json"
        self._write_json(self.catalog_dir / report_name, report)
        return report

    def validate(self, template: dict[str, Any], required: bool = True) -> None:
        # Templates ship already validated; on a node without python3-jsonschema
        # the installer skips the check instead of adding a package to the host.
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            if required:
                raise ConversionError("python3-jsonschema is required to generate templates")
            return
        schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(template), key=lambda error: list(error.path))
        if errors:
            details = "; ".join(f"{'/'.join(map(str, error.path))}: {error.message}" for error in errors)
            raise ConversionError(f"La plantilla generada no cumple el esquema: {details}")

    def compose(self, app_id: str) -> dict[str, Any]:
        """The installable template, built only from the files shipped with
        ProxMenux: the curated profile or the pre-generated template, with its
        overlay applied. Nothing is downloaded and nothing is written."""
        item = self.find_item(app_id)
        if item.get("template_family") == "curated-profile":
            path = self.root / item["curated_path"]
        else:
            path = self.apps_dir / f"{item['id']}.json"
        if not path.exists():
            raise ConversionError(f"No template is available for '{app_id}'")
        template = json.loads(path.read_text(encoding="utf-8"))
        self._apply_overlay(item["id"], template)
        self._apply_category(item["id"], template["catalog_ui"])
        self._apply_volume_policy(item["id"], template["container_contract"])
        self.validate(template, required=False)
        return template

    def load_template(self, app_id: str, generate_if_missing: bool = True) -> dict[str, Any]:
        path = self.apps_dir / f"{app_id}.json"
        if not path.exists() and generate_if_missing:
            _, template = self.generate(app_id)
            return template
        template = json.loads(path.read_text(encoding="utf-8"))
        self.validate(template)
        return template

    def _existing_template_statuses(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if not self.apps_dir.exists():
            return result
        for path in self.apps_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                result[path.stem] = payload.get("status", "unknown")
            except (OSError, json.JSONDecodeError):
                result[path.stem] = "invalid"
        return result

    def _curated_items(self, existing: dict[str, str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if not self.curated_dir.exists():
            return result
        for path in sorted(self.curated_dir.glob("*.json")):
            template = json.loads(path.read_text(encoding="utf-8"))
            self.validate(template)
            app_id = template["id"].removeprefix("image-")
            ui = template["catalog_ui"]
            result.append(
                {
                    "id": app_id,
                    "provider": template["source"]["provider"],
                    "template_family": "curated-profile",
                    "title": ui["title"].get("en_US") or app_id,
                    "repository": template["source"]["repository"],
                    "description": ui["description"].get("en_US") or "",
                    "website": ui.get("website"),
                    "icon": ui.get("icon"),
                    "architectures": supported_architectures(ui["architectures"]),
                    "updated_at": ui.get("updated_at"),
                    "main_image": template["container_contract"]["image"]["reference"],
                    "category": ui["category"],
                    "category_label": ui.get("category_label"),
                    "replaces_discovered_ids": template.get("proxmox", {})
                    .get("catalog", {})
                    .get("replaces_discovered_ids", []),
                    "curated_path": str(path.relative_to(self.root)),
                    "template": f"apps/{app_id}.json" if app_id in existing else None,
                    "template_status": existing.get(app_id),
                    "content_hash": self._template_hash(app_id) if app_id in existing else None,
                }
            )
        return result

    def _apply_overlay(self, app_id: str, template: dict[str, Any]) -> None:
        path = self.overlays_dir / f"{app_id}.json"
        if path.exists():
            overlay = json.loads(path.read_text(encoding="utf-8"))
            self._deep_merge(template, overlay)
        from .stack import apply_stack_support
        apply_stack_support(template)
        from .gpu import apply_gpu_contract
        apply_gpu_contract(template)

    @classmethod
    def _deep_merge(cls, target: dict[str, Any], overlay: dict[str, Any]) -> None:
        for key, value in overlay.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                cls._deep_merge(target[key], value)
            else:
                target[key] = value

    def _update_index_template(self, app_id: str, status: str) -> None:
        index = self.load_index()
        template = json.loads((self.apps_dir / f"{app_id}.json").read_text(encoding="utf-8"))
        ui = template["catalog_ui"]
        for item in index["applications"]:
            if item["id"] == app_id:
                item.update(
                    {
                        "provider": template["source"]["provider"],
                        "title": ui["title"].get("en_US") or app_id,
                        "repository": template["source"]["repository"],
                        "description": ui["description"].get("en_US") or "",
                        "website": ui.get("website"),
                        "icon": ui.get("icon"),
                        "architectures": supported_architectures(ui["architectures"]),
                        "updated_at": ui.get("updated_at"),
                        "main_image": template["container_contract"]["image"]["reference"],
                        "category": ui["category"],
                        "category_label": ui.get("category_label"),
                        "template": f"apps/{app_id}.json",
                        "template_status": status,
                        "automatic_install_candidate": template["compatibility"][
                            "automatic_install_candidate"
                        ],
                        "untranslated_blockers": template["compatibility"][
                            "untranslated_blockers"
                        ],
                        "content_hash": self._template_hash(app_id),
                    }
                )
                if item.get("template_family") == "curated-profile":
                    item["replaces_discovered_ids"] = (
                        template.get("proxmox", {})
                        .get("catalog", {})
                        .get("replaces_discovered_ids", [])
                    )
                break
        self._write_json(self.index_path, index)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _template_hash(self, app_id: str) -> str:
        return hashlib.sha256((self.apps_dir / f"{app_id}.json").read_bytes()).hexdigest()
