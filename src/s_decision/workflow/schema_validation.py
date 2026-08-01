from __future__ import annotations

from pathlib import Path
from typing import Any

from .model import ResponseValidationError, WorkflowDefinition


def resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    current: Any = document
    for part in [part for part in pointer.split("/") if part]:
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            raise ResponseValidationError(f"Unresolved JSON Pointer #{pointer}.")
        current = current[key]
    return current


def schema_document(
    definition: WorkflowDefinition,
    reference: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    relative_path, _, fragment = reference.partition("#")
    path = (definition.source_path.parent / relative_path).resolve()
    document = definition.schemas.get(path)
    if document is None:
        raise ResponseValidationError(f"Schema document is not loaded: {path}")
    schema = resolve_pointer(document, fragment) if fragment else document
    if not isinstance(schema, dict):
        raise ResponseValidationError(f"Schema reference does not resolve to an object: {reference}")
    return document, schema


def json_type_matches(expected: str, value: Any) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def validation_errors(
    schema: dict[str, Any],
    value: Any,
    document: dict[str, Any],
    path: str = "$",
) -> list[str]:
    if "$ref" in schema:
        reference = schema["$ref"]
        if not isinstance(reference, str) or not reference.startswith("#"):
            return [f"{path}: only local $ref values are supported"]
        target = resolve_pointer(document, reference[1:])
        return validation_errors(target, value, document, path)

    if "oneOf" in schema:
        candidates = schema["oneOf"]
        matches = [
            validation_errors(candidate, value, document, path)
            for candidate in candidates
        ]
        passing = [errors for errors in matches if not errors]
        if len(passing) == 1:
            return []
        return [f"{path}: expected exactly one oneOf branch to match"]

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not json_type_matches(expected_type, value):
        return [f"{path}: expected {expected_type}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected constant {schema['const']!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the permitted enumeration")

    if isinstance(value, str):
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            errors.append(f"{path}: string is shorter than {minimum}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for property_name in required:
            if property_name not in value:
                errors.append(f"{path}: missing required property {property_name}")

        properties = schema.get("properties", {})
        for property_name, property_value in value.items():
            if property_name in properties:
                errors.extend(
                    validation_errors(
                        properties[property_name],
                        property_value,
                        document,
                        f"{path}.{property_name}",
                    )
                )
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property {property_name}")

    return errors


def validate_response(
    definition: WorkflowDefinition,
    reference: str | None,
    value: dict[str, Any],
) -> None:
    if reference is None:
        return
    document, schema = schema_document(definition, reference)
    errors = validation_errors(schema, value, document)
    if errors:
        raise ResponseValidationError("; ".join(errors))
