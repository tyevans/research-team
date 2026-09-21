"""Diagnostics and configuration health check for settings and profiles."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from research_team.settings.domain import (
    SETTINGS,
    ScopeRef,
    SettingError,
    SettingSpec,
    dynamic_specs,
    resolve_spec,
)

if TYPE_CHECKING:
    from research_team.settings.application.settings import (
        ModelProfileService,
        SettingsResolver,
    )


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class DiagnosticIssue:
    """One finding discovered during settings diagnostics."""

    code: str
    severity: DiagnosticSeverity
    message: str
    key: str | None = None
    scope: str | None = None
    scope_id: str | None = None
    role: str | None = None
    profile: str | None = None


@dataclass(frozen=True)
class SettingsDiagnostics:
    """Summary of health and configuration issues across a scope chain."""

    issues: tuple[DiagnosticIssue, ...]
    healthy: bool

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is DiagnosticSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is DiagnosticSeverity.WARNING)


async def run_diagnostics(
    resolver: "SettingsResolver",
    profiles: "ModelProfileService | None",
    chain: Iterable[ScopeRef],
) -> SettingsDiagnostics:
    """Analyze resolved settings and profiles for defects, secrets, and misconfigurations."""
    ordered = list(chain)
    issues: list[DiagnosticIssue] = []

    # 1. Stored overrides checks: secret unsealing & parse validation
    if resolver._store is not None:
        stored_rows = await resolver._store.overrides(ordered)
        for row in stored_rows:
            try:
                spec = resolve_spec(row.key)
            except SettingError:
                issues.append(
                    DiagnosticIssue(
                        code="unknown_setting_override",
                        severity=DiagnosticSeverity.WARNING,
                        message=(
                            f"Override {row.key!r} at {row.scope.value} {row.scope_id} "
                            f"names no known setting"
                        ),
                        key=row.key,
                        scope=row.scope.value,
                        scope_id=row.scope_id,
                    )
                )
                continue

            if spec.secret:
                unsealed = resolver._unseal(row.value)
                if unsealed is None:
                    issues.append(
                        DiagnosticIssue(
                            code="unreadable_secret",
                            severity=DiagnosticSeverity.ERROR,
                            message=(
                                f"Secret setting {spec.key!r} at {row.scope.value} "
                                f"{row.scope_id} cannot be decrypted"
                            ),
                            key=spec.key,
                            scope=row.scope.value,
                            scope_id=row.scope_id,
                        )
                    )
            else:
                try:
                    spec.parse(row.value)
                except SettingError as error:
                    issues.append(
                        DiagnosticIssue(
                            code="invalid_stored_value",
                            severity=DiagnosticSeverity.WARNING,
                            message=(
                                f"Stored value for {spec.key!r} at {row.scope.value} "
                                f"{row.scope_id} is invalid ({error}); falling back to default"
                            ),
                            key=spec.key,
                            scope=row.scope.value,
                            scope_id=row.scope_id,
                        )
                    )

    # 2. Conditional dependency checks (required_when)
    all_specs: list[SettingSpec] = [*SETTINGS, *dynamic_specs()]
    specs_by_key = {s.key: s for s in all_specs}
    resolved_settings = {
        r.key: r for r in await resolver.resolve_all(specs_by_key.keys(), ordered)
    }

    # Check transcriber
    transcriber_url = resolved_settings.get("transcriber_url")
    if transcriber_url and transcriber_url.value:
        transcriber_model = resolved_settings.get("transcriber_model")
        if not transcriber_model or not transcriber_model.value:
            issues.append(
                DiagnosticIssue(
                    code="missing_conditional_setting",
                    severity=DiagnosticSeverity.ERROR,
                    message="transcriber_model is required when a transcriber URL is set",
                    key="transcriber_model",
                )
            )

    # Check pgvector
    vector_store = resolved_settings.get("vector_store")
    if vector_store and vector_store.value == "pgvector":
        pgvector_dsn = resolved_settings.get("pgvector_dsn")
        if not pgvector_dsn or not pgvector_dsn.value:
            issues.append(
                DiagnosticIssue(
                    code="missing_conditional_setting",
                    severity=DiagnosticSeverity.ERROR,
                    message="pgvector_dsn is required when the vector store is pgvector",
                    key="pgvector_dsn",
                )
            )

    # Check neo4j
    graph_store = resolved_settings.get("graph_store")
    if graph_store and graph_store.value == "neo4j":
        # Check password
        neo4j_password = await resolver.secret("neo4j_password", ordered)
        if not neo4j_password:
            issues.append(
                DiagnosticIssue(
                    code="missing_conditional_setting",
                    severity=DiagnosticSeverity.ERROR,
                    message="neo4j_password is required when the graph store is neo4j",
                    key="neo4j_password",
                )
            )

    # 3. Role selections and profile checks
    if profiles is not None:
        resolved_roles = await profiles.roles(ordered)
        for r_role in resolved_roles:
            if r_role.dangling is not None:
                issues.append(
                    DiagnosticIssue(
                        code="dangling_profile",
                        severity=DiagnosticSeverity.WARNING,
                        message=(
                            f"Role {r_role.role.value!r} selects profile {r_role.dangling!r} "
                            f"which is not defined in the scope chain; "
                            f"falling back to {r_role.model!r}"
                        ),
                        role=r_role.role.value,
                        profile=r_role.dangling,
                    )
                )
            if r_role.incompatible is not None:
                issues.append(
                    DiagnosticIssue(
                        code="incompatible_profile",
                        severity=DiagnosticSeverity.ERROR,
                        message=r_role.incompatible,
                        role=r_role.role.value,
                        profile=r_role.profile.name if r_role.profile else None,
                    )
                )

        # Check credentials in visible profiles
        visible_profiles = await profiles.profiles(ordered)
        for stored in visible_profiles:
            cred_key = stored.profile.credential_key
            if cred_key is not None:
                try:
                    c_spec = resolve_spec(cred_key)
                    if not c_spec.secret:
                        issues.append(
                            DiagnosticIssue(
                                code="invalid_profile_credential",
                                severity=DiagnosticSeverity.ERROR,
                                message=(
                                    f"Profile {stored.profile.name!r} credential {cred_key!r} "
                                    f"is not a secret setting"
                                ),
                                profile=stored.profile.name,
                                key=cred_key,
                                scope=stored.scope.value,
                                scope_id=stored.scope_id,
                            )
                        )
                except SettingError:
                    issues.append(
                        DiagnosticIssue(
                            code="unresolved_profile_credential",
                            severity=DiagnosticSeverity.WARNING,
                            message=(
                                f"Profile {stored.profile.name!r} references unknown "
                                f"credential key {cred_key!r}"
                            ),
                            profile=stored.profile.name,
                            key=cred_key,
                            scope=stored.scope.value,
                            scope_id=stored.scope_id,
                        )
                    )

    healthy = not any(issue.severity is DiagnosticSeverity.ERROR for issue in issues)
    return SettingsDiagnostics(issues=tuple(issues), healthy=healthy)
