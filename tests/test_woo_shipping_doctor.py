"""Tests for woo_shipping_doctor."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

import woo_shipping_doctor as wsd

HEADER = "zone,order,regions,method,enabled,cost,min_order,requires\n"


def audit_text(text):
    """Audit CSV text and return (zones, findings, summary)."""
    with tempfile.NamedTemporaryFile("w", suffix=".csv",
                                     delete=False) as handle:
        handle.write(text)
        path = handle.name
    try:
        zones, findings, _rows = wsd.audit(path)
    finally:
        os.unlink(path)
    return zones, findings, wsd.summarize(zones, findings)


def rules(findings):
    """Return the sorted list of rule names in the findings."""
    return sorted(f.rule for f in findings)


class TestRegionParsing(unittest.TestCase):
    def test_parse_regions_semicolon(self):
        self.assertEqual(wsd.parse_regions("DE;FR; IT"),
                         ["DE", "FR", "IT"])

    def test_parse_regions_comma(self):
        self.assertEqual(wsd.parse_regions("US, CA"), ["US", "CA"])

    def test_parse_regions_empty(self):
        self.assertEqual(wsd.parse_regions(""), [])
        self.assertEqual(wsd.parse_regions(None), [])

    def test_region_kind(self):
        self.assertEqual(wsd.region_kind("*"), "catchall")
        self.assertEqual(wsd.region_kind("US"), "country")
        self.assertEqual(wsd.region_kind("US:CA"), "state")
        self.assertEqual(wsd.region_kind("90210"), "postcode")
        self.assertEqual(wsd.region_kind("902*"), "postcode")
        self.assertEqual(wsd.region_kind("SW1A*"), "postcode")

    def test_region_kind_invalid(self):
        self.assertIsNone(wsd.region_kind("ZZZ"))
        self.assertIsNone(wsd.region_kind("USA"))
        self.assertIsNone(wsd.region_kind("U"))
        self.assertIsNone(wsd.region_kind("US:"))
        self.assertIsNone(wsd.region_kind("US:CAL"))

    def test_region_covers(self):
        self.assertTrue(wsd.region_covers("*", "US"))
        self.assertTrue(wsd.region_covers("*", "US:CA"))
        self.assertTrue(wsd.region_covers("US", "US"))
        self.assertTrue(wsd.region_covers("US", "US:CA"))
        self.assertFalse(wsd.region_covers("US", "CA"))
        self.assertFalse(wsd.region_covers("US", "MX"))
        self.assertTrue(wsd.region_covers("US:CA", "US:CA"))
        self.assertFalse(wsd.region_covers("US:CA", "US:NY"))
        self.assertTrue(wsd.region_covers("90210", "90210"))
        self.assertFalse(wsd.region_covers("90210", "90211"))

    def test_parse_cost(self):
        self.assertEqual(wsd.parse_cost("9.95"), 9.95)
        self.assertEqual(wsd.parse_cost("1,299.00"), 1299.00)
        self.assertEqual(wsd.parse_cost(" 12 "), 12.0)
        self.assertIsNone(wsd.parse_cost(""))
        self.assertIsNone(wsd.parse_cost("abc"))
        self.assertIsNone(wsd.parse_cost(None))


class TestZoneRules(unittest.TestCase):
    def test_shadowed_region(self):
        _z, findings, _s = audit_text(
            HEADER
            + "United States,1,US,flat_rate,yes,9.95,,\n"
            + "California,2,US:CA,flat_rate,yes,5.00,,\n")
        self.assertIn("shadowed-region", rules(findings))
        shadowed = [f for f in findings if f.rule == "shadowed-region"]
        self.assertEqual(shadowed[0].zone, "California")

    def test_same_country_not_shadowed_by_state(self):
        _z, findings, _s = audit_text(
            HEADER
            + "California,1,US:CA,flat_rate,yes,5.00,,\n"
            + "United States,2,US,flat_rate,yes,9.95,,\n")
        self.assertNotIn("shadowed-region", rules(findings))

    def test_duplicate_zone(self):
        _z, findings, _s = audit_text(
            HEADER
            + "United States,1,US,flat_rate,yes,9.95,,\n"
            + "United States,2,CA,flat_rate,yes,8.00,,\n")
        self.assertIn("duplicate-zone", rules(findings))

    def test_same_zone_multiple_rows_not_duplicate(self):
        _z, findings, _s = audit_text(
            HEADER
            + "United States,1,US,flat_rate,yes,9.95,,\n"
            + "United States,1,US,free_shipping,yes,,50.00,min_amount\n")
        self.assertNotIn("duplicate-zone", rules(findings))

    def test_duplicate_zone_case_insensitive(self):
        _z, findings, _s = audit_text(
            HEADER
            + "United States,1,US,flat_rate,yes,9.95,,\n"
            + "UNITED STATES,2,CA,flat_rate,yes,8.00,,\n")
        self.assertIn("duplicate-zone", rules(findings))

    def test_zone_no_methods_disabled_only(self):
        _z, findings, _s = audit_text(
            HEADER + "Antarctica,1,AQ,flat_rate,no,12.00,,\n")
        self.assertIn("zone-no-methods", rules(findings))

    def test_zone_no_methods_no_rows(self):
        _z, findings, _s = audit_text(HEADER + "Empty Zone,1,,,,,,\n")
        self.assertIn("zone-no-methods", rules(findings))

    def test_zone_no_regions(self):
        _z, findings, _s = audit_text(
            HEADER + "Empty Zone,1,,flat_rate,yes,5.00,,\n")
        self.assertIn("zone-no-regions", rules(findings))

    def test_catchall_not_last(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Rest of the World,1,*,flat_rate,yes,24.95,,\n"
            + "Canada,2,CA,flat_rate,yes,12.00,,\n")
        self.assertIn("catchall-not-last", rules(findings))

    def test_catchall_last_is_clean(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,flat_rate,yes,12.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertNotIn("catchall-not-last", rules(findings))

    def test_missing_catchall(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,12.00,,\n")
        self.assertIn("missing-catchall", rules(findings))

    def test_zones_after_catchall_not_double_flagged(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Rest of the World,1,*,flat_rate,yes,24.95,,\n"
            + "Canada,2,CA,flat_rate,yes,12.00,,\n")
        self.assertNotIn("shadowed-region", rules(findings))
        self.assertEqual(rules(findings).count("catchall-not-last"), 1)

    def test_flat_rate_no_cost(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("flat-rate-no-cost", rules(findings))

    def test_unparseable_cost(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,abc,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("unparseable-cost", rules(findings))

    def test_negative_cost(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,-5.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("negative-cost", rules(findings))

    def test_free_shipping_no_minimum(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,free_shipping,yes,,,min_amount\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("free-shipping-no-minimum", rules(findings))

    def test_free_shipping_unbounded(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,free_shipping,yes,,,none\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("free-shipping-unbounded", rules(findings))

    def test_free_shipping_with_minimum_is_clean(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,free_shipping,yes,,50.00,min_amount\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertEqual(findings, [])

    def test_unknown_method(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,1,CA,table_rate,yes,5.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("unknown-method", rules(findings))

    def test_unknown_requires(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,free_shipping,yes,,,over_100\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("unknown-requires", rules(findings))

    def test_unparseable_min_order(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,free_shipping,yes,,fifty,min_amount\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("unparseable-min-order", rules(findings))

    def test_duplicate_method(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,flat_rate,yes,12.00,,\n"
            + "Canada,1,CA,flat_rate,yes,15.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("duplicate-method", rules(findings))

    def test_duplicate_order(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,flat_rate,yes,12.00,,\n"
            + "Mexico,1,MX,flat_rate,yes,14.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("duplicate-order", rules(findings))

    def test_invalid_region(self):
        _z, findings, _s = audit_text(
            HEADER + "Nowhere,1,ZZZ,flat_rate,yes,5.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("invalid-region", rules(findings))

    def test_invalid_order(self):
        _z, findings, _s = audit_text(
            HEADER + "Canada,soon,CA,flat_rate,yes,12.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("invalid-order", rules(findings))

    def test_malformed_row(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Canada,1,CA,flat_rate,yes,12.00,,\n"
            + "Bad Row,2,CA\n"
            + "Rest of the World,3,*,flat_rate,yes,24.95,,\n")
        self.assertIn("malformed-row", rules(findings))

    def test_missing_zone_name(self):
        _z, findings, _s = audit_text(
            HEADER
            + ",1,CA,flat_rate,yes,12.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertIn("missing-zone", rules(findings))

    def test_postcode_shadow(self):
        _z, findings, _s = audit_text(
            HEADER
            + "London,1,SW1A*,flat_rate,yes,5.00,,\n"
            + "London 2,2,SW1A*,flat_rate,yes,6.00,,\n"
            + "Rest of the World,3,*,flat_rate,yes,24.95,,\n")
        self.assertIn("shadowed-region", rules(findings))

    def test_local_pickup_no_cost_needed(self):
        _z, findings, _s = audit_text(
            HEADER
            + "Local,1,US,local_pickup,yes,,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertEqual(findings, [])

    def test_bom_header(self):
        _z, findings, _s = audit_text(
            "\ufeff" + HEADER
            + "Canada,1,CA,flat_rate,yes,12.00,,\n"
            + "Rest of the World,2,*,flat_rate,yes,24.95,,\n")
        self.assertEqual(findings, [])

    def test_empty_file(self):
        zones, findings, summary = audit_text("")
        self.assertEqual(zones, [])
        self.assertEqual(summary["zones"], 0)


class TestExamples(unittest.TestCase):
    def _example(self, name):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        return os.path.join(base, "examples", name)

    def test_sample_counts(self):
        zones, findings, _rows = wsd.audit(
            self._example("zones.csv"))
        summary = wsd.summarize(zones, findings)
        self.assertEqual(summary,
                         {"zones": 7, "methods": 9, "findings": 10,
                          "errors": 7, "warnings": 3})

    def test_clean_example(self):
        _z, findings, _rows = wsd.audit(self._example("clean.csv"))
        summary = wsd.summarize(_z, findings)
        self.assertEqual(findings, [])
        self.assertEqual(summary["errors"], 0)

    def test_warnings_only_example(self):
        _z, findings, _rows = wsd.audit(
            self._example("warnings-only.csv"))
        summary = wsd.summarize(_z, findings)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(summary["warnings"], 1)


class TestOutput(unittest.TestCase):
    def test_json_shape(self):
        zones, findings, summary = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,12.00,,\n")
        parsed = json.loads(wsd.format_json(zones, findings, summary))
        self.assertEqual(parsed["summary"]["zones"], 1)
        self.assertEqual(parsed["findings"][0]["rule"],
                         "missing-catchall")

    def test_text_summary_line(self):
        zones, findings, summary = audit_text(
            HEADER + "Canada,1,CA,flat_rate,yes,12.00,,\n")
        text = wsd.format_text(zones, findings, summary)
        self.assertIn("Zones: 1, methods: 1, findings: 1, errors: 0, "
                      "warnings: 1", text)

    def test_finding_str(self):
        finding = wsd.Finding("Canada", "CA", "invalid-region",
                              "warning", "bad region")
        self.assertEqual(str(finding),
                         "WARNING [invalid-region] Canada [CA]: bad region")

    def test_check_exit_codes(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        script = os.path.join(base, "woo_shipping_doctor.py")
        clean = os.path.join(base, "examples", "clean.csv")
        sample = os.path.join(base, "examples", "zones.csv")
        warnings_only = os.path.join(base, "examples",
                                     "warnings-only.csv")
        self.assertEqual(subprocess.run(
            [sys.executable, script, clean, "--check"]).returncode, 0)
        self.assertEqual(subprocess.run(
            [sys.executable, script, sample, "--check"]).returncode, 1)
        self.assertEqual(subprocess.run(
            [sys.executable, script, warnings_only, "--check"]
            ).returncode, 0)
        self.assertEqual(subprocess.run(
            [sys.executable, script, warnings_only, "--check",
             "--strict"]).returncode, 1)

    def test_missing_file_exit_code(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        script = os.path.join(base, "woo_shipping_doctor.py")
        result = subprocess.run(
            [sys.executable, script, "no-such-file.csv"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_out_flag(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        script = os.path.join(base, "woo_shipping_doctor.py")
        sample = os.path.join(base, "examples", "clean.csv")
        with tempfile.NamedTemporaryFile("w", suffix=".txt",
                                         delete=False) as handle:
            out_path = handle.name
        try:
            result = subprocess.run(
                [sys.executable, script, sample, "--out", out_path],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            with open(out_path, encoding="utf-8") as handle:
                self.assertIn("All zones clean.", handle.read())
        finally:
            os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
