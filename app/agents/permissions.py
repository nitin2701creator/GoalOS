"""Explicit permission model for GoalOS agents.

Agents never receive unrestricted access. Every agent declares the
permissions it needs, and capabilities map to concrete permissions.
Dangerous permissions (code execution, external writes, sending email,
modifying ads) always require explicit authorization before an agent can
become ACTIVE.
"""

from __future__ import annotations

from app.compat import StrEnum


class Permission(StrEnum):
    """Capabilities an agent is explicitly allowed to exercise."""

    READ_WEBSITE = "READ_WEBSITE"
    WRITE_WEBSITE = "WRITE_WEBSITE"
    READ_EMAIL = "READ_EMAIL"
    SEND_EMAIL = "SEND_EMAIL"
    SEND_WHATSAPP = "SEND_WHATSAPP"
    READ_ANALYTICS = "READ_ANALYTICS"
    MODIFY_ADS = "MODIFY_ADS"
    EXECUTE_CODE = "EXECUTE_CODE"
    READ_FILES = "READ_FILES"
    GENERATE_MEDIA = "GENERATE_MEDIA"
    ACCESS_MEMORY = "ACCESS_MEMORY"
    SCHEDULE_WORKFLOWS = "SCHEDULE_WORKFLOWS"
    READ_CRM = "READ_CRM"
    WRITE_CRM = "WRITE_CRM"
    READ_CALENDAR = "READ_CALENDAR"
    WRITE_CALENDAR = "WRITE_CALENDAR"
    READ_DRIVE = "READ_DRIVE"
    WRITE_DRIVE = "WRITE_DRIVE"
    READ_SOCIAL = "READ_SOCIAL"
    PUBLISH_SOCIAL = "PUBLISH_SOCIAL"
    READ_AUTOMATION = "READ_AUTOMATION"
    EXECUTE_AUTOMATION = "EXECUTE_AUTOMATION"


#: Permissions that can change external state or run code. These are never
#: granted implicitly — they must appear in the agent's declared permissions.
DANGEROUS_PERMISSIONS = frozenset(
    {
        Permission.WRITE_WEBSITE,
        Permission.SEND_EMAIL,
        Permission.SEND_WHATSAPP,
        Permission.MODIFY_ADS,
        Permission.EXECUTE_CODE,
        Permission.GENERATE_MEDIA,
        Permission.SCHEDULE_WORKFLOWS,
        Permission.WRITE_CRM,
        Permission.WRITE_CALENDAR,
        Permission.WRITE_DRIVE,
        Permission.PUBLISH_SOCIAL,
        Permission.EXECUTE_AUTOMATION,
    }
)

#: Deterministic action names derived from permissions for agent specs.
PERMISSION_ACTIONS: dict[Permission, str] = {
    Permission.READ_WEBSITE: "read_website",
    Permission.WRITE_WEBSITE: "write_website",
    Permission.READ_EMAIL: "read_email",
    Permission.SEND_EMAIL: "send_email",
    Permission.SEND_WHATSAPP: "send_whatsapp",
    Permission.READ_ANALYTICS: "read_analytics",
    Permission.MODIFY_ADS: "modify_ads",
    Permission.EXECUTE_CODE: "execute_code",
    Permission.READ_FILES: "read_files",
    Permission.GENERATE_MEDIA: "generate_media",
    Permission.ACCESS_MEMORY: "access_memory",
    Permission.SCHEDULE_WORKFLOWS: "schedule_workflows",
    Permission.READ_CRM: "read_crm",
    Permission.WRITE_CRM: "write_crm",
    Permission.READ_CALENDAR: "read_calendar",
    Permission.WRITE_CALENDAR: "write_calendar",
    Permission.READ_DRIVE: "read_drive",
    Permission.WRITE_DRIVE: "write_drive",
    Permission.READ_SOCIAL: "read_social",
    Permission.PUBLISH_SOCIAL: "publish_social",
    Permission.READ_AUTOMATION: "read_automation",
    Permission.EXECUTE_AUTOMATION: "execute_automation",
}


def actions_for_permissions(permissions: tuple[Permission, ...]) -> tuple[str, ...]:
    """Return the deterministic allowed actions for ``permissions``."""
    return tuple(
        PERMISSION_ACTIONS[permission]
        for permission in sorted(permissions, key=lambda item: item.value)
    )
