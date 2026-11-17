"""Deterministic, fail-closed comparison of independently captured observations.

This module never runs a target and never accepts a candidate's self-reported
verdict. Only frozen obligations and the two selected pieces of evidence count.
"""
from __future__ import annotations

import json
import math
import re
from .analysis import json_shape

_MAX_COMPARE_BYTES = 16 * 1024 * 1024
_MAX_PIXELS = 1024 * 1024
_MISSING = object()
_DEFAULTS = {"behavior": "stdout", "state": "state", "side-effects": "effects",
             "structure": "structure", "visual": "visual"}


class _EvidenceError(ValueError):
    pass


def _validate_json(value, depth=0):
    if depth > 64:
        raise _EvidenceError("JSON nesting exceeds 64 levels")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        for item in value.values():
            _validate_json(item, depth + 1)
        return
    raise _EvidenceError("Selected value is not finite JSON data")


def _json(value):
    if isinstance(value, str):
        if len(value.encode("utf-8")) > _MAX_COMPARE_BYTES:
            raise _EvidenceError("JSON byte limit exceeded")
        def invalid(constant):
            raise _EvidenceError("Non-finite JSON number: " + constant)
        def pairs(items):
            result = {}
            for k, v in items:
                if k in result:
                    raise _EvidenceError("Duplicate JSON object key: " + k)
                result[k] = v
            return result
        try:
            value = json.loads(value, parse_constant=invalid, object_pairs_hook=pairs)
        except (ValueError, RecursionError) as exc:
            raise _EvidenceError("Invalid JSON: " + str(exc)) from exc
    _validate_json(value)
    return value


def _exact(left, right):
    # Avoid Python's True == 1 and recursive containers of that same ambiguity.
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return (left.keys() == right.keys()
                and all(_exact(left[k], right[k]) for k in left))
    if isinstance(left, list):
        return len(left) == len(right) and all(_exact(a, b) for a, b in zip(left, right))
    return left == right


def _json_equal(left, right):
    if (isinstance(left, (int, float)) and not isinstance(left, bool)
            and isinstance(right, (int, float)) and not isinstance(right, bool)):
        return left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return _exact(left, right)


def _select(capture, selector):
    # An exact field wins (including a literal filename containing '/'). Nested
    # selections use JSON Pointer, or dotted keys as a convenience. Never eval.
    if selector in capture:
        return capture[selector]
    if selector.startswith("/"):
        parts = [p.replace("~1", "/").replace("~0", "~") for p in selector[1:].split("/")]
    elif "." in selector:
        parts = selector.split(".")
    else:
        return _MISSING
    current = capture
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return _MISSING
    return current


def _quality(capture, side):
    issues = []
    if not isinstance(capture, dict):
        return [side + " capture is not an object"]
    if capture.get("status") not in ("completed", "succeeded"):
        issues.append(side + " capture status is not completed/succeeded: " + str(capture.get("status", "missing")))
    for key in ("output_truncated", "truncated", "stdout_truncated", "stderr_truncated"):
        if capture.get(key) is not None and capture.get(key) is not False:
            issues.append(side + " capture has " + key)
    if capture.get("error") not in (None, "", False):
        issues.append(side + " capture has an execution error")
    cleanup = capture.get("cleanup", _MISSING)
    if cleanup is _MISSING:
        issues.append(side + " cleanup evidence missing")
    else:
        state = cleanup.get("state") if isinstance(cleanup, dict) else cleanup
        if state != "complete":
            issues.append(side + " cleanup is not complete")
    return issues


def _error_envelope(value):
    if not isinstance(value, dict):
        return False
    return (value.get("error") not in (None, "", False)
            or value.get("status") in ("unknown", "blocked", "truncated", "missing", "failed")
            or value.get("truncated") is True)


def _state_error(value):
    """Recognize collection-error envelopes at file-map and direct-selector levels."""
    return (_error_envelope(value)
            or (isinstance(value, dict) and any(_error_envelope(v) for v in value.values())))


def _shape_descriptor(value, depth=0):
    if depth > 64 or not isinstance(value, dict):
        return False
    kind = value.get("type")
    if kind in ("null", "boolean", "number", "string"):
        return set(value) == {"type"}
    if kind == "object":
        properties = value.get("properties")
        return (set(value) == {"type", "properties"} and isinstance(properties, dict)
                and all(isinstance(k, str) and _shape_descriptor(v, depth + 1)
                        for k, v in properties.items()))
    if kind == "array":
        items = value.get("items")
        return (set(value) == {"type", "items"} and isinstance(items, list)
                and all(_shape_descriptor(v, depth + 1) for v in items))
    return False


def _ppm(value):
    if isinstance(value, str):
        try:
            data = value.encode("ascii")
        except UnicodeError as exc:
            raise _EvidenceError("PPM text must be ASCII; use bytes for P6 raster") from exc
    elif isinstance(value, bytes):
        data = value
    else:
        raise _EvidenceError("PPM must be actual P3/P6 bytes or ASCII text")
    if len(data) > _MAX_COMPARE_BYTES:
        raise _EvidenceError("PPM byte limit exceeded")
    whitespace = b" \t\r\n\v\f"
    index = 0

    def token():
        nonlocal index
        while index < len(data):
            if data[index] in whitespace:
                index += 1
            elif data[index] == 35:
                end = data.find(b"\n", index)
                index = len(data) if end < 0 else end + 1
            else:
                break
        start = index
        while index < len(data) and data[index] not in whitespace and data[index] != 35:
            index += 1
        if index == start or index - start > 32:
            raise _EvidenceError("PPM missing/oversized token")
        return data[start:index]

    def number():
        t = token()
        if not re.fullmatch(rb"[0-9]+", t):
            raise _EvidenceError("PPM integer token malformed")
        return int(t)

    magic = token()
    if magic not in (b"P3", b"P6"):
        raise _EvidenceError("Unsupported image format; only P3/P6 PPM")
    width, height, maximum = number(), number(), number()
    if width <= 0 or height <= 0 or width * height > _MAX_PIXELS:
        raise _EvidenceError("PPM dimensions outside bounded pixel budget")
    if not 1 <= maximum <= 65535:
        raise _EvidenceError("PPM maxval outside 1..65535")
    samples = width * height * 3
    if magic == b"P3":
        pixels = [number() for _ in range(samples)]
        # Only trailing whitespace/comments permitted; reject surplus samples.
        while index < len(data):
            if data[index] in whitespace:
                index += 1
            elif data[index] == 35:
                end = data.find(b"\n", index)
                index = len(data) if end < 0 else end + 1
            else:
                raise _EvidenceError("PPM trailing data or extra samples")
    else:
        if index >= len(data) or data[index] not in whitespace:
            raise _EvidenceError("P6 raster separator missing")
        # A P6 header ends with one whitespace delimiter, never skip arbitrary
        # whitespace here: the first pixel itself can be 0x20, 0x0A, or '#'.
        stride = 2 if maximum > 255 else 1
        if (data[index:index + 2] == b"\r\n"
                and len(data) - index - 2 == samples * stride):
            index += 2
        else:
            index += 1
        raster = data[index:]
        if len(raster) != samples * stride:
            raise _EvidenceError("P6 raster length does not match dimensions")
        if stride == 1:
            pixels = list(raster)
        else:
            pixels = [raster[i] * 256 + raster[i + 1] for i in range(0, len(raster), 2)]
    if any(v > maximum for v in pixels):
        raise _EvidenceError("PPM sample exceeds maxval")
    return width, height, maximum, pixels


def _summary(value):
    """Bound result size; differences never echo entire captures or binary bytes."""
    if isinstance(value, bytes):
        return {"type": "bytes", "size": len(value)}
    if isinstance(value, str):
        return {"type": "string", "length": len(value), "preview": value[:200]}
    if isinstance(value, (dict, list)):
        return {"type": type(value).__name__, "length": len(value)}
    return value


def compare_observations(left: dict, right: dict, plan: dict) -> dict:
    """Evaluate every frozen obligation without executing or mutating evidence.

    Nonzero *expected* business exits are comparable when capture quality is
    completed/succeeded; failed run quality stays blocked. Cleanup is required.
    structure is a precomputed external JSON-shape descriptor; json-shape on
    other selected fields derives that descriptor from decoded JSON values.
    """
    result = {"status": "blocked", "obligations": [], "differences": [], "limitations": []}
    quality = _quality(left, "left") + _quality(right, "right")
    if quality:
        result["limitations"].extend(quality)
        result["limitations"].append("Expected nonzero business exits require collector expect_exit/status mapping; failed capture quality is never upgraded here.")
    obligations = plan.get("obligations") if isinstance(plan, dict) else None
    if not isinstance(obligations, list) or not obligations:
        result["limitations"].append("Plan requires a nonempty frozen obligations array")
        return result
    seen = set()
    for index, obligation in enumerate(obligations):
        item = {"id": None, "dimension": None, "status": "blocked", "differences": [],
                "coverage": {"left_present": False, "right_present": False}}
        result["obligations"].append(item)

        def issue(reason, status="blocked", **fields):
            item["status"] = status
            difference = {"obligation_id": item["id"], "dimension": item["dimension"],
                          "reason": reason, **fields}
            item["differences"].append(difference)
            result["differences"].append(difference)

        if not isinstance(obligation, dict):
            issue("Obligation must be an object", index=index)
            continue
        identifier = obligation.get("id")
        dimension = obligation.get("dimension")
        item["id"] = identifier if isinstance(identifier, str) else None
        item["dimension"] = dimension if isinstance(dimension, str) else None
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            issue("Obligation id missing/invalid/duplicate", index=index)
            continue
        seen.add(identifier)
        if not isinstance(dimension, str) or dimension not in _DEFAULTS:
            issue("Unsupported or missing dimension")
            continue
        blocking = obligation.get("blocking", True)
        if not isinstance(blocking, bool):
            issue("blocking must be boolean")
            continue
        item["blocking"] = blocking
        if "not_applicable_reason" in obligation:
            reason = obligation["not_applicable_reason"]
            if (not isinstance(obligation.get("comparator"), str)
                    or obligation["comparator"] not in {"exact", "json", "json-shape", "ppm"}):
                issue("not-applicable obligation still requires a valid frozen comparator")
            elif not isinstance(reason, str) or not reason.strip():
                issue("not-applicable requires a frozen nonempty reason")
            else:
                item["status"] = "not-applicable"
                item["not_applicable_reason"] = reason
                item["coverage"]["reason"] = reason
            continue
        comparator = obligation.get("comparator")
        selector = obligation.get("selector", _DEFAULTS[dimension])
        item["comparator"] = comparator if isinstance(comparator, str) else None
        item["coverage"]["selector"] = selector if isinstance(selector, str) else None
        if not isinstance(selector, str) or not selector:
            issue("selector must be a nonempty capture field or JSON Pointer")
            continue
        if not isinstance(left, dict) or not isinstance(right, dict):
            issue("Capture must be an object")
            continue
        lvalue, rvalue = _select(left, selector), _select(right, selector)
        item["coverage"].update(left_present=lvalue is not _MISSING, right_present=rvalue is not _MISSING)
        if lvalue is _MISSING or rvalue is _MISSING:
            issue("Selected capture field missing")
            continue
        if quality:
            issue("Capture execution/collection quality blocks acceptance", quality=quality)
            continue
        if dimension == "state" and (_state_error(lvalue) or _state_error(rvalue)):
            issue("Selected state contains a collection error/unknown envelope")
            continue
        if selector == "state" and (not isinstance(lvalue, dict) or not isinstance(rvalue, dict)):
            issue("State capture must map selected file paths to decoded JSON")
            continue
        if selector == "effects":
            valid = lambda value: (isinstance(value, dict) and all(
                isinstance(k, str) and isinstance(v, str) and re.fullmatch(r"[0-9a-fA-F]{64}", v)
                for k, v in value.items()))
            if not valid(lvalue) or not valid(rvalue):
                issue("Side-effects capture must map paths to complete SHA-256 digests")
                continue
        if selector == "structure" and (not _shape_descriptor(lvalue) or not _shape_descriptor(rvalue)):
            issue("External JSON structure is missing, unknown or not a supported shape descriptor")
            continue
        if selector in {"stdout", "stderr"} and (not isinstance(lvalue, str) or not isinstance(rvalue, str)):
            issue("stdout/stderr evidence must be text")
            continue
        if not isinstance(comparator, str) or comparator not in {"exact", "json", "json-shape", "ppm"}:
            issue("Unsupported comparator", "inconclusive")
            continue
        if dimension == "visual" and comparator != "ppm":
            issue("Visual obligation requires actual PPM pixel comparator", "inconclusive")
            continue
        if comparator == "ppm" and dimension != "visual":
            issue("PPM comparator applies only to visual evidence", "inconclusive")
            continue
        try:
            if comparator == "ppm":
                lw, lh, lm, lp = _ppm(lvalue)
                rw, rh, rm, rp = _ppm(rvalue)
                item["coverage"].update(left_dimensions=[lw, lh], right_dimensions=[rw, rh],
                                        left_pixels=lw * lh, right_pixels=rw * rh)
                if (lw, lh) != (rw, rh):
                    issue("PPM dimensions differ", "fail", left=[lw, lh], right=[rw, rh])
                else:
                    different = sum(any(lp[p + c] * rm != rp[p + c] * lm for c in range(3))
                                    for p in range(0, len(lp), 3))
                    item["coverage"]["different_pixels"] = different
                    if different:
                        issue("PPM pixels differ", "fail", different_pixels=different,
                              total_pixels=lw * lh)
                    else:
                        item["status"] = "pass"
            else:
                if comparator == "exact":
                    _validate_json(lvalue)
                    _validate_json(rvalue)
                    equal = _exact(lvalue, rvalue)
                else:
                    ljson, rjson = _json(lvalue), _json(rvalue)
                    if comparator == "json-shape" and selector != "structure":
                        ljson, rjson = json_shape(ljson), json_shape(rjson)
                    equal = _json_equal(ljson, rjson)
                if equal:
                    item["status"] = "pass"
                else:
                    issue("Selected evidence differs", "fail", left=_summary(lvalue), right=_summary(rvalue))
        except (ValueError, TypeError, RecursionError, OverflowError) as exc:
            issue("Malformed/unsupported evidence: " + str(exc), "inconclusive")
    statuses = [item["status"] for item in result["obligations"]]
    if quality or "blocked" in statuses:
        result["status"] = "blocked"
    elif "fail" in statuses:
        result["status"] = "fail"
    elif "inconclusive" in statuses:
        result["status"] = "inconclusive"
    elif "pass" in statuses:
        result["status"] = "pass"
    else:
        result["status"] = "inconclusive"
        result["limitations"].append("All obligations are not-applicable; no positive comparison coverage")
    return result
