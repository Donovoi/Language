#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO_PATH = ROOT / "proto/session.proto"
PYTHON_OUTPUT = ROOT / "services/gateway/app/generated/session_contract.py"
DART_OUTPUT = ROOT / "apps/field_app_flutter/lib/generated/session_contract.dart"

ENUM_SPECS = {
    "SessionMode": {
        "proto_prefix": "SESSION_MODE_",
        "python_name": "SessionMode",
        "dart_name": "SessionMode",
        "members": {
            "UNSPECIFIED": {
                "api": "UNSPECIFIED",
                "dart_member": "unspecified",
                "label": "Unspecified",
            },
            "FOCUS": {
                "api": "FOCUS",
                "dart_member": "focus",
                "label": "Focus",
            },
            "CROWD": {
                "api": "CROWD",
                "dart_member": "crowd",
                "label": "Crowd",
            },
            "LOCKED": {
                "api": "LOCKED",
                "dart_member": "locked",
                "label": "Locked",
            },
        },
    },
    "LaneStatus": {
        "proto_prefix": "LANE_STATUS_",
        "python_name": "LaneStatus",
        "dart_name": "TranslationLaneStatus",
        "members": {
            "UNSPECIFIED": {
                "api": "UNSPECIFIED",
                "dart_member": "unspecified",
                "label": "Pending",
            },
            "IDLE": {
                "api": "IDLE",
                "dart_member": "idle",
                "label": "Idle",
            },
            "LISTENING": {
                "api": "LISTENING",
                "dart_member": "listening",
                "label": "Listening",
            },
            "TRANSLATING": {
                "api": "TRANSLATING",
                "dart_member": "translating",
                "label": "Translating",
            },
            "READY": {
                "api": "READY",
                "dart_member": "ready",
                "label": "Ready",
            },
            "ERROR": {
                "api": "ERROR",
                "dart_member": "error",
                "label": "Error",
            },
        },
    },
    "StreamEventType": {
        "proto_prefix": "STREAM_EVENT_TYPE_",
        "python_name": "StreamEventType",
        "dart_name": "SessionStreamEventType",
        "members": {
            "UNSPECIFIED": {
                "api": "unknown",
                "dart_member": "unknown",
            },
            "SESSION_SNAPSHOT": {
                "api": "session.snapshot",
                "dart_member": "sessionSnapshot",
            },
            "SPEAKER_UPDATE": {
                "api": "speaker.update",
                "dart_member": "speakerUpdate",
            },
        },
    },
}

PYTHON_MODEL_SPECS = {
    "SpeakerState": "SpeakerState",
    "SessionResponse": "SessionState",
    "SpeakerEventResponse": "SpeakerEvent",
    "SessionStreamEvent": "SessionStreamEvent",
}

DART_MESSAGE_SPECS = {
    "SpeakerState": {
        "list_name": "kSpeakerContractFields",
        "field_consts": {
            "speaker_id": "kSpeakerIdJsonKey",
            "display_name": "kSpeakerDisplayNameJsonKey",
            "language_code": "kSpeakerLanguageCodeJsonKey",
            "priority": "kSpeakerPriorityJsonKey",
            "active": "kSpeakerActiveJsonKey",
            "is_locked": "kSpeakerIsLockedJsonKey",
            "front_facing": "kSpeakerFrontFacingJsonKey",
            "persistence_bonus": "kSpeakerPersistenceBonusJsonKey",
            "last_updated_unix_ms": "kSpeakerLastUpdatedUnixMsJsonKey",
            "source_caption": "kSpeakerSourceCaptionJsonKey",
            "translated_caption": "kSpeakerTranslatedCaptionJsonKey",
            "target_language_code": "kSpeakerTargetLanguageCodeJsonKey",
            "lane_status": "kSpeakerLaneStatusJsonKey",
            "status_message": "kSpeakerStatusMessageJsonKey",
        },
    },
    "SessionState": {
        "list_name": "kSessionStateContractFields",
        "field_consts": {
            "session_id": "kSessionStateSessionIdJsonKey",
            "mode": "kSessionStateModeJsonKey",
            "speakers": "kSessionStateSpeakersJsonKey",
            "top_speaker_id": "kSessionStateTopSpeakerIdJsonKey",
        },
    },
    "SpeakerEvent": {
        "list_name": "kSpeakerEventContractFields",
        "field_consts": {
            "speaker_id": "kSpeakerEventSpeakerIdJsonKey",
            "priority_delta": "kSpeakerEventPriorityDeltaJsonKey",
            "active": "kSpeakerEventActiveJsonKey",
            "is_locked": "kSpeakerEventIsLockedJsonKey",
            "observed_unix_ms": "kSpeakerEventObservedUnixMsJsonKey",
            "source_caption": "kSpeakerEventSourceCaptionJsonKey",
            "translated_caption": "kSpeakerEventTranslatedCaptionJsonKey",
            "target_language_code": "kSpeakerEventTargetLanguageCodeJsonKey",
            "lane_status": "kSpeakerEventLaneStatusJsonKey",
            "status_message": "kSpeakerEventStatusMessageJsonKey",
        },
    },
    "SessionStreamEvent": {
        "list_name": "kSessionStreamEventContractFields",
        "field_consts": {
            "event": "kSessionStreamEventEventJsonKey",
            "session": "kSessionStreamEventSessionJsonKey",
            "speaker_event": "kSessionStreamEventSpeakerEventJsonKey",
        },
    },
}


def parse_proto(path: Path) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    text = path.read_text(encoding="utf-8")
    enums: dict[str, list[str]] = {}
    messages: dict[str, list[str]] = {}

    for name, body in re.findall(r"enum\s+(\w+)\s*\{(.*?)\}", text, re.DOTALL):
        enums[name] = re.findall(
            r"^\s*([A-Z0-9_]+)\s*=\s*\d+\s*;",
            body,
            re.MULTILINE,
        )

    for name, body in re.findall(r"message\s+(\w+)\s*\{(.*?)\}", text, re.DOTALL):
        messages[name] = re.findall(
            r"^\s*(?:repeated\s+)?(?:[\w.]+)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*\d+\s*;",
            body,
            re.MULTILINE,
        )

    return enums, messages


def build_python_output(enums: dict[str, list[str]], messages: dict[str, list[str]]) -> str:
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "from enum import Enum",
        "",
        "# Generated by scripts/generate_contract_bindings.py from proto/session.proto.",
        "# Do not edit by hand.",
        "",
        "CONTRACT_LOCKED_PROTO_ENUMS = {",
    ]

    for enum_name, spec in ENUM_SPECS.items():
        lines.extend(
            [
                f'    "{spec["python_name"]}": {{',
                f'        "proto_enum": "{enum_name}",',
                '        "members": {',
            ]
        )
        for proto_member in enums[enum_name]:
            member_name = proto_member.removeprefix(spec["proto_prefix"])
            member_spec = spec["members"][member_name]
            lines.extend(
                [
                    f'            "{member_name}": {{',
                    f'                "proto": "{proto_member}",',
                    f'                "api": "{member_spec["api"]}",',
                    "            },",
                ]
            )
        lines.extend(["        },", "    },"])

    lines.extend(["}", "", "CONTRACT_LOCKED_PROTO_MODELS = {"])
    for model_name, proto_message in PYTHON_MODEL_SPECS.items():
        lines.extend(
            [
                f'    "{model_name}": {{',
                f'        "proto_message": "{proto_message}",',
                '        "fields": (',
            ]
        )
        for field in messages[proto_message]:
            lines.append(f'            "{field}",')
        lines.extend(["        ),", "    },"])
    lines.extend(["}", ""])

    for enum_name, spec in ENUM_SPECS.items():
        lines.append(f'class {spec["python_name"]}(str, Enum):')
        for proto_member in enums[enum_name]:
            member_name = proto_member.removeprefix(spec["proto_prefix"])
            member_spec = spec["members"][member_name]
            lines.append(f'    {member_name} = "{member_spec["api"]}"')
        lines.append("")

    lines.extend(
        [
            "__all__ = [",
            '    "CONTRACT_LOCKED_PROTO_ENUMS",',
            '    "CONTRACT_LOCKED_PROTO_MODELS",',
        ]
    )
    for spec in ENUM_SPECS.values():
        lines.append(f'    "{spec["python_name"]}",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def build_dart_output(enums: dict[str, list[str]], messages: dict[str, list[str]]) -> str:
    lines: list[str] = [
        "// Generated by scripts/generate_contract_bindings.py from proto/session.proto.",
        "// Do not edit by hand.",
        "",
    ]

    for message_name, spec in DART_MESSAGE_SPECS.items():
        for field_name in messages[message_name]:
            const_name = spec["field_consts"][field_name]
            lines.append(f"const String {const_name} = '{field_name}';")
        lines.append("")
        lines.append(f"const List<String> {spec['list_name']} = <String>[")
        for field_name in messages[message_name]:
            const_name = spec["field_consts"][field_name]
            lines.append(f"  {const_name},")
        lines.extend(["];", ""])

    for enum_name, spec in ENUM_SPECS.items():
        lines.append(f"enum {spec['dart_name']} {{")
        proto_members = enums[enum_name]
        for index, proto_member in enumerate(proto_members):
            member_name = proto_member.removeprefix(spec["proto_prefix"])
            member_spec = spec["members"][member_name]
            suffix = "," if index < len(proto_members) - 1 else ";"
            if "label" in member_spec:
                lines.append(
                    "  "
                    f"{member_spec['dart_member']}('{proto_member}', '{member_spec['api']}', '{member_spec['label']}'){suffix}"
                )
            else:
                lines.append(
                    "  "
                    f"{member_spec['dart_member']}('{proto_member}', '{member_spec['api']}'){suffix}"
                )
        lines.append("")
        if any("label" in spec["members"][member.removeprefix(spec["proto_prefix"])] for member in proto_members):
            lines.append(
                f"  const {spec['dart_name']}(this.protoName, this.apiValue, this.label);"
            )
            lines.append("")
            lines.append("  final String protoName;")
            lines.append("  final String apiValue;")
            lines.append("  final String label;")
        else:
            lines.append(f"  const {spec['dart_name']}(this.protoName, this.apiValue);")
            lines.append("")
            lines.append("  final String protoName;")
            lines.append("  final String apiValue;")
        lines.append("}")
        lines.append("")
        lines.append(f"extension {spec['dart_name']}Presentation on {spec['dart_name']} {{")
        lines.append("")
        lines.append(f"  static {spec['dart_name']} fromApiValue(String? value) {{")
        lines.append(f"    return {spec['dart_name']}.values.firstWhere(")
        lines.append("      (item) => item.apiValue == value,")
        lines.append(
            f"      orElse: () => {spec['dart_name']}.{spec['members'][proto_members[0].removeprefix(spec['proto_prefix'])]['dart_member']},"
        )
        lines.append("    );")
        lines.append("  }")
        lines.append("}")
        lines.append("")

    return "\n".join(lines)


def write_if_changed(path: Path, content: str) -> bool:
    normalized = content.rstrip() + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == normalized:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalized, encoding="utf-8")
    return True


def check_matches(path: Path, content: str) -> bool:
    normalized = content.rstrip() + "\n"
    return path.exists() and path.read_text(encoding="utf-8") == normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify generated outputs are up to date without writing files.",
    )
    args = parser.parse_args()

    enums, messages = parse_proto(PROTO_PATH)
    python_output = build_python_output(enums, messages)
    dart_output = build_dart_output(enums, messages)

    if args.check:
        stale_paths = [
            str(path.relative_to(ROOT))
            for path, content in (
                (PYTHON_OUTPUT, python_output),
                (DART_OUTPUT, dart_output),
            )
            if not check_matches(path, content)
        ]
        if stale_paths:
            print("Generated contract bindings are out of date:", file=sys.stderr)
            for path in stale_paths:
                print(f"- {path}", file=sys.stderr)
            print("Run `python3 scripts/generate_contract_bindings.py` to refresh them.", file=sys.stderr)
            return 1
        print("Generated contract bindings are up to date.")
        return 0

    changed = [
        str(path.relative_to(ROOT))
        for path, content in (
            (PYTHON_OUTPUT, python_output),
            (DART_OUTPUT, dart_output),
        )
        if write_if_changed(path, content)
    ]
    if changed:
        print("Updated generated contract bindings:")
        for path in changed:
            print(f"- {path}")
    else:
        print("Generated contract bindings already up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
