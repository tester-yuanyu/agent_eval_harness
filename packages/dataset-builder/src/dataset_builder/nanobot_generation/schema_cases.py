"Deterministic schema examples, explicitly separate from runtime semantics."

import copy
import json

from jsonschema import Draft202012Validator


def sample(schema):
    if schema.get("x-python-only"):
        return None
    if "enum" in schema:
        return copy.deepcopy(schema["enum"][0])
    if "const" in schema:
        return copy.deepcopy(schema["const"])
    if "anyOf" in schema:
        return sample(
            next(
                (s for s in schema["anyOf"] if s.get("type") != "null"),
                schema["anyOf"][0],
            )
        )
    typ = schema.get("type", "object" if "properties" in schema else "string")
    if isinstance(typ, list):
        typ = next((t for t in typ if t != "null"), "null")
    if typ == "object":
        props = schema.get("properties", {})
        value = {k: sample(v) for k, v in props.items()}
        for name in schema.get("required", []):
            value.setdefault(name, sample(props.get(name, {})))
        forbidden = schema.get("not", {})
        if "required" in forbidden and Draft202012Validator(forbidden).is_valid(value):
            for name in forbidden["required"]:
                if Draft202012Validator(props.get(name, {})).is_valid(None):
                    value[name] = None
                    break
                if name not in schema.get("required", []):
                    value.pop(name, None)
                    break
        return value
    if typ == "array":
        return [
            sample(schema.get("items", {}))
            for _ in range(max(1, schema.get("minItems", 0)))
        ]
    if typ == "string":
        return "x" * max(1, schema.get("minLength", 0))
    if typ in {"integer", "number"}:
        return schema.get("minimum", 0)
    if typ == "boolean":
        return False
    if typ == "null":
        return None
    raise ValueError(f"unsupported schema type: {typ}")


def schema_examples(schema):
    Draft202012Validator.check_schema(schema)

    def supported(value):
        if isinstance(value, dict):
            if {
                "pattern",
                "$ref",
                "oneOf",
                "allOf",
                "if",
                "contains",
                "uniqueItems",
                "multipleOf",
                "exclusiveMinimum",
                "exclusiveMaximum",
            } & value.keys():
                raise ValueError(
                    "unsupported schema constraint; needs explicit strategy"
                )
            if "not" in value:
                forbidden = value["not"]
                allowed_const = set(forbidden) == {"const"}
                allowed_pair = set(forbidden) == {"required", "properties"}
                if not (allowed_const or allowed_pair):
                    raise ValueError("unsupported not constraint")
            for key in ("properties", "$defs"):
                for child in value.get(key, {}).values():
                    supported(child)
            for key in ("items", "additionalProperties"):
                if isinstance(value.get(key), dict):
                    supported(value[key])
            for child in value.get("anyOf", []):
                supported(child)
        elif isinstance(value, list):
            for child in value:
                supported(child)

    supported(schema)
    base = sample(schema)
    validator = Draft202012Validator(schema)
    if not validator.is_valid(base):
        raise ValueError("unsupported schema: cannot construct valid baseline")
    found = {}

    def add(value, dimension):
        key = json.dumps(value, sort_keys=True, ensure_ascii=False)
        if key not in found:
            found[key] = {
                "instance": value,
                "expected_valid": validator.is_valid(value),
                "dimensions": [],
            }
        if dimension not in found[key]["dimensions"]:
            found[key]["dimensions"].append(dimension)

    def change(path, value, dimension, remove=False):
        obj = copy.deepcopy(base)
        if not path:
            obj = value
        else:
            cursor = obj
            for part in path[:-1]:
                cursor = cursor[part]
            if remove:
                del cursor[path[-1]]
            else:
                cursor[path[-1]] = value
        add(obj, dimension)

    def walk(node, path):
        prefix = "/" + "/".join(map(str, path))
        for value in (None, True, 3, 1.5, "x", [], {}):
            change(path, value, prefix + ":type:" + type(value).__name__)
        if "const" in node:
            change(path, node["const"], prefix + ":const")
            change(path, "__outside_const__", prefix + ":outside_const")
        forbidden = node.get("not", {})
        if "const" in forbidden:
            change(path, forbidden["const"], prefix + ":forbidden_const")
        elif "required" in forbidden:
            banned = sample(node)
            for name in forbidden["required"]:
                banned[name] = sample(forbidden["properties"].get(name, {}))
            change(path, banned, prefix + ":forbidden_combination")
        for index, value in enumerate(node.get("enum", [])):
            change(path, value, f"{prefix}:enum:{index}")
        if "enum" in node:
            change(path, "__outside_enum__", prefix + ":outside_enum")
        for key in ("minimum", "maximum"):
            if key in node:
                limit = node[key]
                change(path, limit, prefix + ":" + key)
                change(
                    path,
                    limit + (-1 if key == "minimum" else 1),
                    prefix + ":outside_" + key,
                )
        for key in ("minLength", "maxLength"):
            if key in node:
                limit = node[key]
                change(path, "x" * limit, prefix + ":" + key)
                outside = limit + (-1 if key == "minLength" else 1)
                if outside >= 0:
                    change(path, "x" * outside, prefix + ":outside_" + key)
        for key in ("minItems", "maxItems"):
            if key in node:
                limit = node[key]
                item = sample(node.get("items", {}))
                change(
                    path,
                    [copy.deepcopy(item) for _ in range(limit)],
                    prefix + ":" + key,
                )
                outside = limit + (-1 if key == "minItems" else 1)
                if outside >= 0:
                    change(
                        path,
                        [copy.deepcopy(item) for _ in range(outside)],
                        prefix + ":outside_" + key,
                    )
        types = node.get("type", [])
        types = [types] if isinstance(types, str) else types
        if node.get("x-python-only"):
            return  # JSON examples cannot manufacture Python AgentHook objects.
        if "object" in types or "properties" in node:
            required = node.get("required", [])
            value = sample(node)
            change(
                path,
                {k: v for k, v in value.items() if k in required},
                prefix + ":required_only",
            )
            change(path, {**value, "__extra__": 1}, prefix + ":additional_property")
            properties = dict(node.get("properties", {}))
            for name in node.get("required", []):
                properties.setdefault(name, {})
            for name, child in properties.items():
                change(
                    path + [name], None, prefix + "/" + name + ":omitted", remove=True
                )
                walk(child, path + [name])
            extra_schema = node.get("additionalProperties")
            if isinstance(extra_schema, dict):
                change(
                    path,
                    {"fixture_key": sample(extra_schema)},
                    prefix + ":additional_value_valid",
                )
                for val in (None, "wrong", [], True):
                    change(
                        path,
                        {"fixture_key": val},
                        prefix + ":additional_value:" + type(val).__name__,
                    )
        if "array" in types:
            walk(node.get("items", {}), path + [0])
        for variant in node.get("anyOf", []):
            change(path, sample(variant), prefix + ":union")
            walk(variant, path)

    add(base, "baseline")
    walk(schema, [])
    return list(found.values())
