#!/usr/bin/env python3
"""Validate the external audio corpus catalog."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_CATALOG = Path("fixtures/audio_eval/external_corpora/catalog.json")
REQUIRED_CORPUS_FIELDS = {
    "id",
    "name",
    "priority",
    "status",
    "license_status",
    "roles",
    "languages",
    "size_notes",
    "access",
    "recommended_first_use",
    "why_it_matters",
    "detractor_note",
    "sources",
}
VALID_STATUSES = {"approved_candidate", "review_required", "deferred"}
VALID_PRIORITIES = {"p0", "p1", "p2"}
REQUIRED_P0_ROLES = {
    "real_room_meeting",
    "crowd_noise",
    "diarization",
    "speech_separation",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _validate_source(corpus_id: str, source: dict[str, Any]) -> None:
    _require(isinstance(source.get("type"), str) and source["type"], f"{corpus_id}: source missing type")
    url = source.get("url")
    _require(isinstance(url, str) and url.startswith("https://"), f"{corpus_id}: source URL must be https")
    evidence = source.get("evidence")
    _require(isinstance(evidence, str) and len(evidence) >= 20, f"{corpus_id}: source evidence is too thin")


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    _require(catalog.get("schema_version") == 1, "schema_version must be 1")
    _require(isinstance(catalog.get("policy"), dict), "policy block is required")
    role_definitions = catalog.get("role_definitions")
    _require(isinstance(role_definitions, dict) and role_definitions, "role_definitions block is required")
    corpora = catalog.get("corpora")
    _require(isinstance(corpora, list) and corpora, "corpora must be a non-empty list")

    ids: set[str] = set()
    p0_roles: set[str] = set()
    warnings: list[str] = []
    for corpus in corpora:
        _require(isinstance(corpus, dict), "each corpus entry must be an object")
        missing = REQUIRED_CORPUS_FIELDS.difference(corpus)
        corpus_id = str(corpus.get("id", "<missing>"))
        _require(not missing, f"{corpus_id}: missing required fields {sorted(missing)}")
        _require(corpus_id not in ids, f"duplicate corpus id {corpus_id}")
        _require(corpus_id == corpus_id.lower(), f"{corpus_id}: id must be lowercase")
        _require(" " not in corpus_id, f"{corpus_id}: id must not contain spaces")
        ids.add(corpus_id)

        _require(corpus["priority"] in VALID_PRIORITIES, f"{corpus_id}: invalid priority")
        _require(corpus["status"] in VALID_STATUSES, f"{corpus_id}: invalid status")
        roles = corpus["roles"]
        _require(isinstance(roles, list) and roles, f"{corpus_id}: roles must be a non-empty list")
        unknown_roles = sorted(set(roles).difference(role_definitions))
        _require(not unknown_roles, f"{corpus_id}: unknown roles {unknown_roles}")
        if corpus["priority"] == "p0":
            p0_roles.update(str(role) for role in roles)

        sources = corpus["sources"]
        _require(isinstance(sources, list) and sources, f"{corpus_id}: sources must be a non-empty list")
        for source in sources:
            _validate_source(corpus_id, source)

        if corpus["status"] == "approved_candidate" and "review" in str(corpus["license_status"]):
            warnings.append(f"{corpus_id}: approved_candidate has review-like license_status")
        if corpus["status"] == "review_required" and "benchmark-only" not in corpus["detractor_note"].lower():
            warnings.append(f"{corpus_id}: review_required entry should explain benchmark-only/product-demo limits")

    missing_roles = REQUIRED_P0_ROLES.difference(p0_roles)
    _require(not missing_roles, f"p0 catalog must cover roles {sorted(missing_roles)}")

    for deferred in catalog.get("deferred_or_rejected", []):
        _require(isinstance(deferred.get("id"), str) and deferred["id"], "deferred item missing id")
        _require(isinstance(deferred.get("reason"), str) and len(deferred["reason"]) >= 20, "deferred reason too thin")

    return warnings


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the external audio corpus catalog")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    catalog_path = args.catalog.resolve()
    with catalog_path.open("r", encoding="utf-8") as handle:
        catalog = json.load(handle)
    warnings = validate_catalog(catalog)
    print(f"audio corpus catalog PASS: {catalog_path}")
    for warning in warnings:
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
