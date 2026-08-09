"""Lightweight JSON Schema validator for Fangcun Next schemas.

The schemas under references/schemas use a deliberately small subset of
draft-07 so the runtime has zero mandatory third-party dependencies:
type, properties, required, additionalProperties, items, enum, minItems,
minLength and pattern.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .common import read_json, schemas_dir


class SchemaValidationError(ValueError):
    def __init__(self, messages: list[str]):
        self.messages = messages
        super().__init__("; ".join(messages))


def load_schema(name: str) -> dict:
    path = schemas_dir() / name
    if not path.exists():
        raise SchemaValidationError([f"schema file not found: {name}"])
    return read_json(path, {})


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _validate_node(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 值必须为 {schema['const']!r}")

    if "oneOf" in schema:
        branch_results: list[list[str]] = []
        for branch in schema.get("oneOf", []):
            branch_errors: list[str] = []
            _validate_node(value, branch, path, branch_errors)
            branch_results.append(branch_errors)
        matched = sum(1 for branch_errors in branch_results if not branch_errors)
        if matched != 1:
            errors.append(f"{path}: 必须且只能满足 oneOf 中的一个结构（实际匹配 {matched} 个）")
            if matched == 0 and branch_results:
                shortest = min(branch_results, key=len)
                errors.extend(shortest[:3])
            return

    if "anyOf" in schema:
        matched = False
        branch_results: list[list[str]] = []
        for branch in schema.get("anyOf", []):
            branch_errors: list[str] = []
            _validate_node(value, branch, path, branch_errors)
            branch_results.append(branch_errors)
            if not branch_errors:
                matched = True
        if not matched:
            errors.append(f"{path}: 至少满足 anyOf 中的一个结构")
            if branch_results:
                errors.extend(min(branch_results, key=len)[:3])

    if "allOf" in schema:
        for branch in schema.get("allOf", []):
            _validate_node(value, branch, path, errors)

    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, list):
            if not any(_type_ok(value, t) for t in expected_type):
                errors.append(f"{path}: 期望类型 {expected_type}，实际 {type(value).__name__}")
                return
        elif not _type_ok(value, expected_type):
            errors.append(f"{path}: 期望类型 {expected_type}，实际 {type(value).__name__}")
            return

    if isinstance(value, dict) and schema.get("type") in ("object", None):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                errors.append(f"{path}: 缺少必填字段 {required}")
        additional = schema.get("additionalProperties")
        if additional is False:
            allowed = set(properties)
            for key in value:
                if key not in allowed:
                    errors.append(f"{path}: 不允许的字段 {key}")
        elif isinstance(additional, dict):
            for key in set(value) - set(properties):
                _validate_node(value[key], additional, f"{path}.{key}" if path else key, errors)
        for key, sub in properties.items():
            if key in value:
                _validate_node(value[key], sub, f"{path}.{key}" if path else key, errors)

    if isinstance(value, list):
        items = schema.get("items")
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            errors.append(f"{path}: 至少需要 {min_items} 项")
        max_items = schema.get("maxItems")
        if max_items is not None and len(value) > max_items:
            errors.append(f"{path}: 最多允许 {max_items} 项")
        if schema.get("uniqueItems") and len({json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value}) != len(value):
            errors.append(f"{path}: 数组项必须唯一")
        if isinstance(items, dict):
            for idx, item in enumerate(value):
                _validate_node(item, items, f"{path}[{idx}]", errors)

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度不能少于 {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: 不符合模式 {schema['pattern']}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 值 {value!r} 不在允许列表 {schema['enum']}")

    if "minimum" in schema and isinstance(value, (int, float)) and value < schema["minimum"]:
        errors.append(f"{path}: 不能小于 {schema['minimum']}")
    if "maximum" in schema and isinstance(value, (int, float)) and value > schema["maximum"]:
        errors.append(f"{path}: 不能大于 {schema['maximum']}")


def validate(data: Any, schema_name: str) -> tuple[bool, list[str]]:
    schema = load_schema(schema_name)
    errors: list[str] = []
    _validate_node(data, schema, "$", errors)
    return (not errors), errors


def ensure_valid(data: Any, schema_name: str) -> None:
    ok, errors = validate(data, schema_name)
    if not ok:
        raise SchemaValidationError(errors)


def dump_schema_json(schema_name: str) -> str:
    return json.dumps(load_schema(schema_name), ensure_ascii=False, indent=2)
