"""Five-dimension comparison qualification, without targets or network access."""
import copy
import json
import unittest

from traceanchor.analysis import json_shape
from traceanchor.comparison import compare_observations


def capture(**changes):
    result = {"status": "completed", "exit_code": 0, "stdout": "ok\n", "stderr": "",
              "cleanup": {"state": "complete"}, "output_truncated": False,
              "state": {"state.json": {"count": 1}}, "effects": {"out.txt": "a" * 64},
              "structure": json_shape({"count": 1}),
              "visual": "P3\n1 1\n255\n255 0 0\n"}
    result.update(changes)
    return result


def plan(*dimensions, comparator=None, selector=None):
    obligations = []
    for dimension in dimensions:
        item = {"id": dimension, "dimension": dimension,
                "comparator": comparator or ("ppm" if dimension == "visual" else "exact"),
                "blocking": True}
        if selector is not None:
            item["selector"] = selector
        obligations.append(item)
    return {"obligations": obligations}


class ComparisonTests(unittest.TestCase):
    def test_five_dimensions_independent_positive_and_json_serializable(self):
        left, right = capture(), capture()
        frozen = plan("behavior", "state", "side-effects", "structure", "visual")
        original_left = copy.deepcopy(left)
        original_plan = copy.deepcopy(frozen)
        result = compare_observations(left, right, frozen)
        self.assertEqual(result["status"], "pass")
        self.assertEqual([o["status"] for o in result["obligations"]], ["pass"] * 5)
        self.assertEqual(left, original_left)
        self.assertEqual(frozen, original_plan)
        json.dumps(result)

    def test_correct_picture_wrong_behavior_is_not_overall_pass(self):
        result = compare_observations(capture(), capture(stdout="wrong"), plan("behavior", "visual"))
        self.assertEqual(result["status"], "fail")
        self.assertEqual([o["status"] for o in result["obligations"]], ["fail", "pass"])
        self.assertTrue(result["differences"])

    def test_state_and_side_effect_differences(self):
        for dimension, replacement in (("state", {"state.json": {"count": 2}}),
                                       ("side-effects", {"out.txt": "b" * 64})):
            key = "effects" if dimension == "side-effects" else dimension
            result = compare_observations(capture(), capture(**{key: replacement}), plan(dimension))
            self.assertEqual(result["status"], "fail")
            self.assertEqual(result["obligations"][0]["dimension"], dimension)

    def test_precomputed_structure_descriptors_not_resummarized(self):
        left = capture(structure=json_shape({"answer": 1}))
        right = capture(structure=json_shape({"answer": "wrong type"}))
        result = compare_observations(left, right, plan("structure", comparator="json-shape"))
        self.assertEqual(result["status"], "fail")
        right["structure"] = json_shape({"answer": 900})
        self.assertEqual(compare_observations(left, right, plan("structure", comparator="json-shape"))["status"], "pass")

    def test_json_values_vs_json_shape(self):
        left, right = capture(stdout='{"answer":1,"items":[true]}'), capture(stdout='{"items":[false], "answer":99}')
        self.assertEqual(compare_observations(left, right, plan("behavior", comparator="json"))["status"], "fail")
        self.assertEqual(compare_observations(left, right, plan("structure", comparator="json-shape", selector="stdout"))["status"], "pass")
        right["stdout"] = '{"items":[0],"answer":99}'
        self.assertEqual(compare_observations(left, right, plan("structure", comparator="json-shape", selector="stdout"))["status"], "fail")

    def test_exact_exit_stderr_and_false_zero_empty_are_present(self):
        for field, value in (("exit_code", 0), ("stdout", ""), ("flag", False)):
            result = compare_observations(capture(**{field: value}), capture(**{field: value}),
                                          plan("behavior", selector=field))
            self.assertEqual(result["status"], "pass")
        for field in ("exit_code", "stderr"):
            replacement = 2 if field == "exit_code" else "unexpected error"
            result = compare_observations(capture(), capture(**{field: replacement}), plan("behavior", selector=field))
            self.assertEqual(result["status"], "fail")
        self.assertEqual(compare_observations(capture(flag=False), capture(flag=0), plan("behavior", selector="flag"))["status"], "fail")

    def test_missing_fields_are_blocked_not_equal_empty(self):
        for dimension, key in (("behavior", "stdout"), ("state", "state"),
                               ("side-effects", "effects"), ("structure", "structure"), ("visual", "visual")):
            left, right = capture(), capture()
            del left[key]
            del right[key]
            result = compare_observations(left, right, plan(dimension))
            self.assertEqual(result["status"], "blocked")
            self.assertFalse(result["obligations"][0]["coverage"]["left_present"])

    def test_failed_unknown_timeout_output_limit_and_cleanup_quality_block(self):
        bad = [{"status": s} for s in ("failed", "timed_out", "cancelled", "unknown", "output_limit", "truncated")]
        bad += [{"output_truncated": True}, {"stdout_truncated": True}, {"stderr_truncated": True},
                {"cleanup": {"state": "pending"}}, {"cleanup": "unknown"}, {"error": "collector failed"}]
        for changes in bad:
            with self.subTest(changes=changes):
                result = compare_observations(capture(), capture(**changes), plan("behavior"))
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["obligations"][0]["status"], "blocked")
        right = capture()
        del right["cleanup"]
        self.assertEqual(compare_observations(capture(), right, plan("behavior"))["status"], "blocked")

    def test_expected_business_exit_only_after_collector_status_mapping(self):
        left, right = capture(exit_code=2, stdout="", stderr="bad input"), capture(exit_code=2, stdout="", stderr="bad input")
        frozen = plan("behavior", selector="exit_code")
        self.assertEqual(compare_observations(left, right, frozen)["status"], "pass")
        right["status"] = "failed"
        result = compare_observations(left, right, frozen)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("expect_exit" in item for item in result["limitations"]))
        right.update(status="completed", process_status="failed")
        self.assertEqual(compare_observations(left, right, frozen)["status"], "pass")

    def test_state_collection_error_unknown_envelopes_block(self):
        for error in ({"error": "file missing"}, {"status": "unknown"}, {"status": "truncated"}):
            result = compare_observations(capture(state={"selected.json": error}),
                                          capture(state={"selected.json": error}), plan("state", comparator="json"))
            self.assertEqual(result["status"], "blocked")

    def test_exact_selector_is_not_candidate_self_report(self):
        right = capture(stdout="wrong", passed=True, verdict="pass")
        self.assertEqual(compare_observations(capture(), right, plan("behavior"))["status"], "fail")
        # Literal capture field names take precedence over pointer syntax.
        left = capture(**{"exit_code/stdout": "pair"})
        right = capture(**{"exit_code/stdout": "pair"})
        self.assertEqual(compare_observations(left, right, plan("behavior", selector="exit_code/stdout"))["status"], "pass")

    def test_json_pointer_and_dotted_selectors(self):
        left, right = capture(), capture()
        for selector in ("/state/state.json/count", "state"):
            self.assertEqual(compare_observations(left, right, plan("state", selector=selector))["status"], "pass")
        left["sample"] = {"values": [0, False]}
        right["sample"] = {"values": [0, False]}
        self.assertEqual(compare_observations(left, right, plan("state", selector="sample.values.1"))["status"], "pass")
        self.assertEqual(compare_observations(left, right, plan("state", selector="/sample/values/4"))["status"], "blocked")

    def test_json_malformed_duplicate_and_nonfinite_inconclusive(self):
        for malformed in ('{"x":', '{"x":NaN}', '{"x":1,"x":2}', '{"x":Infinity}'):
            result = compare_observations(capture(stdout=malformed), capture(stdout=malformed),
                                          plan("behavior", comparator="json"))
            self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(compare_observations(capture(stdout="true"), capture(stdout="1"), plan("behavior", comparator="json"))["status"], "fail")

    def test_ppm_p3_p6_pixels_comments_and_normalized_maxval(self):
        left = capture(visual="P3\n# fixture\n1 1\n255\n255 0 0\n")
        right = capture(visual=b"P6\n1 1\n255\n\xff\x00\x00")
        result = compare_observations(left, right, plan("visual"))
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["obligations"][0]["coverage"]["different_pixels"], 0)
        right["visual"] = "P3 1 1 1 1 0 0"
        self.assertEqual(compare_observations(left, right, plan("visual"))["status"], "pass")
        # Big-endian 16-bit P6 sample support.
        right["visual"] = b"P6\n1 1\n65535\n\xff\xff\x00\x00\x00\x00"
        self.assertEqual(compare_observations(left, right, plan("visual"))["status"], "pass")
        # Initial raster bytes that look like whitespace/comments remain pixels.
        right["visual"] = b"P6\n1 1\n255\n\x0a\x20#"
        left["visual"] = "P3 1 1 255 10 32 35"
        self.assertEqual(compare_observations(left, right, plan("visual"))["status"], "pass")
        right["visual"] = b"P6\n1 1\n255\r\n\x20#"
        self.assertEqual(compare_observations(left, right, plan("visual"))["status"], "pass")
        right["visual"] = b"P6\r\n1 1\r\n255\r\n\x0a\x20#"
        self.assertEqual(compare_observations(left, right, plan("visual"))["status"], "pass")

    def test_ppm_pixel_and_dimension_differences(self):
        result = compare_observations(capture(), capture(visual="P3 1 1 255 0 255 0"), plan("visual"))
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["obligations"][0]["coverage"]["different_pixels"], 1)
        result = compare_observations(capture(), capture(visual="P3 2 1 255 255 0 0 255 0 0"), plan("visual"))
        self.assertEqual(result["status"], "fail")
        self.assertIn("dimensions", result["differences"][0]["reason"])

    def test_ppm_bad_formats_truncated_and_budget_inconclusive(self):
        bad_images = [b"\x89PNG\r\n", b"P6\n1 1\n255\n\xff", "P3 0 1 255", "P3 1 1 255 999 0 0",
                      "P3 1 1 255 1 2 3 4", "P3 1 1 0 0 0 0", "P3 999999999 999999999 255",
                      "P3 1 1 255 -1 0 0", {"passed": True}]
        for visual in bad_images:
            with self.subTest(visual=visual):
                result = compare_observations(capture(visual=visual), capture(visual=visual), plan("visual"))
                self.assertEqual(result["status"], "inconclusive")
        result = compare_observations(capture(), capture(), plan("visual", comparator="exact"))
        self.assertEqual(result["status"], "inconclusive")

    def test_not_applicable_reason_frozen_and_no_silent_removal(self):
        frozen = plan("behavior", "visual")
        frozen["obligations"][1]["not_applicable_reason"] = "CLI fixture has no image output"
        left, right = capture(), capture()
        del left["visual"]
        del right["visual"]
        result = compare_observations(left, right, frozen)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(len(result["obligations"]), 2)
        self.assertEqual(result["obligations"][1]["status"], "not-applicable")
        self.assertEqual(result["obligations"][1]["not_applicable_reason"], "CLI fixture has no image output")
        frozen["obligations"][1]["not_applicable_reason"] = " "
        self.assertEqual(compare_observations(left, right, frozen)["status"], "blocked")

    def test_only_not_applicable_is_inconclusive_and_quality_still_blocks(self):
        frozen = plan("visual")
        frozen["obligations"][0]["not_applicable_reason"] = "No image in specification"
        self.assertEqual(compare_observations(capture(), capture(), frozen)["status"], "inconclusive")
        self.assertEqual(compare_observations(capture(), capture(status="failed"), frozen)["status"], "blocked")

    def test_malformed_plans_and_capture_are_fail_closed(self):
        malformed = [None, {}, {"obligations": []}, {"obligations": [None]},
                     {"obligations": [{"id": "x", "dimension": [], "comparator": "exact"}]},
                     {"obligations": [{"id": [], "dimension": "behavior", "comparator": "exact"}]}]
        for frozen in malformed:
            self.assertEqual(compare_observations(capture(), capture(), frozen)["status"], "blocked")
        frozen = plan("behavior")
        frozen["obligations"].append(copy.deepcopy(frozen["obligations"][0]))
        self.assertEqual(compare_observations(capture(), capture(), frozen)["status"], "blocked")
        self.assertEqual(compare_observations(None, {}, plan("behavior"))["status"], "blocked")
        self.assertEqual(compare_observations(capture(status=[]), capture(), plan("behavior"))["status"], "blocked")
        frozen = plan("behavior")
        frozen["obligations"][0]["comparator"] = []
        self.assertEqual(compare_observations(capture(), capture(), frozen)["status"], "inconclusive")

    def test_unknown_structure_and_invalid_effect_hashes_block(self):
        for shape in (None, {"error": "parse failed"}, {"type": "unknown"}, "unknown"):
            self.assertEqual(compare_observations(capture(structure=shape), capture(structure=shape),
                                                  plan("structure"))["status"], "blocked")
        for effects in ({"out.txt": "partial"}, {"out.txt": None}, {"out.txt": {"error": "failed"}}, None):
            self.assertEqual(compare_observations(capture(effects=effects), capture(effects=effects),
                                                  plan("side-effects"))["status"], "blocked")
        self.assertEqual(compare_observations(capture(effects={}), capture(effects={}),
                                              plan("side-effects"))["status"], "pass")

    def test_direct_selected_state_error_is_not_equal_success(self):
        left = capture(state={"s.json": {"error": "read failed"}})
        result = compare_observations(left, copy.deepcopy(left), plan("state", selector="/state/s.json"))
        self.assertEqual(result["status"], "blocked")
        left = capture(state={"s.json": None})
        self.assertEqual(compare_observations(left, copy.deepcopy(left), plan("state"))["status"], "pass")

    def test_unsupported_comparator_does_not_silently_pass(self):
        self.assertEqual(compare_observations(capture(), capture(), plan("behavior", comparator="similarity"))["status"], "inconclusive")


if __name__ == "__main__":
    unittest.main()
