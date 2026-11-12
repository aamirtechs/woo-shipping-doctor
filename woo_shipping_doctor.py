"""WooCommerce shipping zones audit CLI.

Reads a CSV export of WooCommerce shipping zones and audits it
for the configuration mistakes that cause "no shipping options
at checkout" and wrong-rate tickets: zones with no enabled
methods, duplicate zone names, regions shadowed by an earlier
zone (WooCommerce matches zones top to bottom and stops at the
first match, so a specific zone below a broad one never fires),
a catch-all zone that is not last, a missing catch-all zone,
flat rates with no cost, free shipping with no minimum, and
regions that are not a valid country, state, postcode, or
catch-all.

The zone-matching rule enforced here is WooCommerce's own:
zones are matched top to bottom and the customer gets the first
zone that matches (WooCommerce documentation, "Setting up
shipping zones"; WooCommerce troubleshooting guide for core
shipping, woocommerce.com/document/troubleshooting-core-shipping).
A country region covers that country and its states, a state
region covers only itself, a postcode covers only itself, and
the catch-all region * covers everything.

Each problem is a finding with a zone, a rule name, a severity
(error or warning), and a message. Errors are the ones that
break checkout or charge the wrong rate; warnings are hygiene
issues worth fixing. --check exits 1 when any error is found,
and --strict also fails on warnings.

Zero dependencies, Python 3.10 or newer, standard library only.

Usage:
    python3 woo_shipping_doctor.py examples/zones.csv
    python3 woo_shipping_doctor.py zones.csv --json --check
"""

import argparse
import csv
import json
import re
import sys

__version__ = "1.0.0"

KNOWN_METHODS = {"flat_rate", "free_shipping", "local_pickup"}

FREE_SHIPPING_REQUIRES = {"none", "min_amount", "coupon", "either", "both"}

COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
STATE_RE = re.compile(r"^[A-Z]{2}:[A-Z]{2}$")
POSTCODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9 *\-]{0,11}$")


class Finding:
    """One audit finding for one zone, region, or method."""

    def __init__(self, zone, detail, rule, severity, message):
        self.zone = zone
        self.detail = detail
        self.rule = rule
        self.severity = severity
        self.message = message

    def as_dict(self):
        """Return the finding as a plain dict."""
        return {"zone": self.zone, "detail": self.detail,
                "rule": self.rule, "severity": self.severity,
                "message": self.message}

    def __str__(self):
        target = self.zone
        if self.detail is not None:
            target = "%s [%s]" % (self.zone, self.detail)
        return "%s [%s] %s: %s" % (self.severity.upper(), self.rule,
                                   target, self.message)


def parse_regions(field):
    """Split a regions field into a list of regions.

    Regions are separated by semicolons or commas. Empty segments
    are dropped.
    """
    if field is None:
        return []
    parts = re.split(r"[;,]", field)
    return [part.strip().upper() for part in parts if part.strip()]


def region_kind(region):
    """Classify a region, or return None when it is not valid.

    Valid regions are the catch-all *, a two-letter country code,
    a state code like US:CA, or a postcode pattern (letters and
    digits with an optional wildcard, so it must contain a digit,
    a wildcard, a dash, or a space to count as a postcode rather
    than a mistyped country code).
    """
    if region == "*":
        return "catchall"
    if COUNTRY_RE.match(region):
        return "country"
    if STATE_RE.match(region):
        return "state"
    if POSTCODE_RE.match(region) and re.search(r"[0-9*\- ]", region):
        return "postcode"
    return None


def region_covers(upper, lower):
    """Return True when region upper covers region lower.

    The catch-all covers everything, a country covers itself and
    its states, and a state or postcode covers only itself.
    """
    if upper == "*":
        return True
    if COUNTRY_RE.match(upper):
        return lower == upper or lower.startswith(upper + ":")
    return upper == lower


def parse_cost(value):
    """Parse a cost string to a float, or return None.

    A blank value returns None without an error; the caller
    decides whether a blank cost is a problem for that method.
    An unparseable non-blank value also returns None, and the
    caller reports it through the original string.
    """
    if value is None:
        return None
    value = value.strip().replace(",", "")
    if value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


class Zone:
    """One shipping zone, in the order it appears in the file."""

    def __init__(self, name, order):
        self.name = name
        self.order = order
        self.regions = []
        self.methods = []

    def enabled_methods(self):
        """Return the methods that are switched on."""
        return [m for m in self.methods if m["enabled"]]


def load_zones(path):
    """Read the zones CSV and return (zones, findings, row_count).

    Rows are grouped into zones by name, keeping the order each
    zone first appears in. A row with a blank method registers
    the zone but adds no method, so a zone with no method rows
    at all can still be audited.
    """
    zones = []
    by_name = {}
    flagged_duplicates = set()
    findings = []
    row_count = 0
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return zones, findings, row_count
        expected = len(header)
        for line_no, row in enumerate(reader, start=2):
            if not row or all(not cell.strip() for cell in row):
                continue
            row_count += 1
            if len(row) != expected:
                findings.append(Finding(
                    "(file)", "row %d" % line_no, "malformed-row",
                    "error",
                    "row has %d fields but the header has %d, so the "
                    "row was skipped" % (len(row), expected)))
                continue
            record = dict(zip(header, row))
            name = (record.get("zone") or "").strip()
            if not name:
                findings.append(Finding(
                    "(file)", "row %d" % line_no, "missing-zone",
                    "error", "row has no zone name, so it was skipped"))
                continue
            order_text = (record.get("order") or "").strip()
            try:
                order = int(order_text) if order_text else 9999
            except ValueError:
                findings.append(Finding(
                    name, "row %d" % line_no, "invalid-order",
                    "warning",
                    "order %r is not a number, so the zone was placed "
                    "last" % order_text))
                order = 9999
            key = name.lower()
            if key in by_name:
                zone = by_name[key]
                if key not in flagged_duplicates and order != zone.order:
                    flagged_duplicates.add(key)
                    findings.append(Finding(
                        name, "order %d" % order, "duplicate-zone",
                        "error",
                        "zone name %r already appears at order %d, so "
                        "the two zones are the same name twice"
                        % (name, zone.order)))
            else:
                zone = Zone(name, order)
                zones.append(zone)
                by_name[key] = zone
            for region in parse_regions(record.get("regions")):
                if region not in zone.regions:
                    zone.regions.append(region)
            method = (record.get("method") or "").strip().lower()
            if not method:
                continue
            enabled_text = (record.get("enabled") or "").strip().lower()
            zone.methods.append({
                "method": method,
                "enabled": enabled_text in ("yes", "true", "1", "on"),
                "cost": record.get("cost") or "",
                "min_order": record.get("min_order") or "",
                "requires": (record.get("requires") or "").strip().lower(),
                "line": line_no,
            })
    indexed = list(enumerate(zones))
    indexed.sort(key=lambda pair: (pair[1].order, pair[0]))
    zones = [zone for _index, zone in indexed]
    return zones, findings, row_count


def audit_zones(zones):
    """Run the zone rules and return a list of findings."""
    findings = []
    seen_orders = {}
    for zone in zones:
        if zone.order in seen_orders and zone.order != 9999:
            findings.append(Finding(
                zone.name, "order %d" % zone.order, "duplicate-order",
                "warning",
                "order %d is also used by zone %r, so the match order "
                "between them is ambiguous"
                % (zone.order, seen_orders[zone.order])))
        else:
            seen_orders[zone.order] = zone.name
    catchall_index = None
    for index, zone in enumerate(zones):
        if "*" in zone.regions:
            catchall_index = index
            break
    if catchall_index is None:
        findings.append(Finding(
            "(zone set)", None, "missing-catchall", "warning",
            "no zone covers *, so a customer outside every defined "
            "zone reaches checkout with no shipping method available"))
    elif catchall_index != len(zones) - 1:
        below = len(zones) - catchall_index - 1
        findings.append(Finding(
            zones[catchall_index].name, "*", "catchall-not-last",
            "error",
            "the catch-all zone matches every address, so the %d "
            "zone(s) below it never match" % below))
    for index, zone in enumerate(zones):
        if not zone.regions:
            findings.append(Finding(
                zone.name, None, "zone-no-regions", "warning",
                "zone has no regions, so it matches no address"))
        for region in zone.regions:
            if region_kind(region) is None:
                findings.append(Finding(
                    zone.name, region, "invalid-region", "warning",
                    "region %r is not a country code, a state code, a "
                    "postcode pattern, or *" % region))
        if not zone.enabled_methods():
            findings.append(Finding(
                zone.name, None, "zone-no-methods", "error",
                "zone has no enabled shipping method, so customers "
                "matching it see no shipping options at checkout"))
        seen_methods = {}
        for method in zone.methods:
            name = method["method"]
            if name in seen_methods:
                findings.append(Finding(
                    zone.name, name, "duplicate-method", "warning",
                    "method %r appears twice in this zone, so only "
                    "the first one takes effect" % name))
            else:
                seen_methods[name] = True
            if name not in KNOWN_METHODS:
                findings.append(Finding(
                    zone.name, name, "unknown-method", "warning",
                    "method %r is not a WooCommerce core method "
                    "(flat_rate, free_shipping, local_pickup), so it "
                    "comes from an extension" % name))
            if name == "flat_rate":
                cost = parse_cost(method["cost"])
                if method["cost"].strip() == "":
                    findings.append(Finding(
                        zone.name, name, "flat-rate-no-cost", "error",
                        "flat rate has no cost, so checkout shows a "
                        "zero or missing rate"))
                elif cost is None:
                    findings.append(Finding(
                        zone.name, name, "unparseable-cost", "error",
                        "flat rate cost %r is not a number"
                        % method["cost"].strip()))
                elif cost < 0:
                    findings.append(Finding(
                        zone.name, name, "negative-cost", "error",
                        "flat rate cost %.2f is negative" % cost))
            if name == "free_shipping":
                requires = method["requires"]
                if requires and requires not in FREE_SHIPPING_REQUIRES:
                    findings.append(Finding(
                        zone.name, name, "unknown-requires", "warning",
                        "free shipping condition %r is not one of none, "
                        "min_amount, coupon, either, or both" % requires))
                if requires == "min_amount":
                    if method["min_order"].strip() == "":
                        findings.append(Finding(
                            zone.name, name,
                            "free-shipping-no-minimum", "warning",
                            "free shipping requires a minimum order "
                            "amount but none is set, so it never "
                            "triggers"))
                    elif parse_cost(method["min_order"]) is None:
                        findings.append(Finding(
                            zone.name, name, "unparseable-min-order",
                            "warning",
                            "free shipping minimum %r is not a number"
                            % method["min_order"].strip()))
                elif requires in ("", "none"):
                    findings.append(Finding(
                        zone.name, name, "free-shipping-unbounded",
                        "warning",
                        "free shipping applies to every order with no "
                        "condition, so every order in this zone ships "
                        "free"))
        if catchall_index is not None and index > catchall_index:
            continue
        for earlier in zones[:index]:
            if "*" in earlier.regions:
                continue
            for region in zone.regions:
                if region_kind(region) is None:
                    continue
                for upper in earlier.regions:
                    if region_covers(upper, region):
                        findings.append(Finding(
                            zone.name, region, "shadowed-region",
                            "error",
                            "region is already covered by zone %r "
                            "(order %d), which matches first, so this "
                            "zone never matches it"
                            % (earlier.name, earlier.order)))
                        break
    return findings


def audit(path):
    """Audit one zones file and return (zones, findings, rows)."""
    zones, load_findings, row_count = load_zones(path)
    findings = load_findings + audit_zones(zones)
    return zones, findings, row_count


def summarize(zones, findings):
    """Build the summary dict for one audit."""
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = sum(1 for f in findings if f.severity == "warning")
    methods = sum(len(z.methods) for z in zones)
    return {"zones": len(zones), "methods": methods,
            "findings": len(findings), "errors": errors,
            "warnings": warnings}


def format_text(zones, findings, summary):
    """Render the audit as plain text."""
    lines = [str(f) for f in findings]
    lines.append("")
    lines.append("Zones: %d, methods: %d, findings: %d, errors: %d, "
                 "warnings: %d" % (summary["zones"], summary["methods"],
                                   summary["findings"], summary["errors"],
                                   summary["warnings"]))
    if not findings:
        lines.append("All zones clean.")
    return "\n".join(lines) + "\n"


def format_json(zones, findings, summary):
    """Render the audit as JSON."""
    return json.dumps({"summary": summary,
                       "findings": [f.as_dict() for f in findings]},
                      indent=2) + "\n"


def main(argv=None):
    """Entry point for the woo-shipping-doctor CLI."""
    parser = argparse.ArgumentParser(
        description="Audit a WooCommerce shipping zones CSV export "
                    "for configuration mistakes.")
    parser.add_argument("path", help="CSV file of shipping zones")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON instead of text")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any error is found")
    parser.add_argument("--strict", action="store_true",
                        help="with --check, also exit 1 on warnings")
    parser.add_argument("--out", help="write the report to a file")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    try:
        zones, findings, _rows = audit(args.path)
    except FileNotFoundError:
        print("error: file not found: %s" % args.path, file=sys.stderr)
        return 2
    except OSError as exc:
        print("error: cannot read %s: %s" % (args.path, exc),
              file=sys.stderr)
        return 2
    summary = summarize(zones, findings)
    if args.json:
        output = format_json(zones, findings, summary)
    else:
        output = format_text(zones, findings, summary)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output, end="")
    if args.check:
        if summary["errors"]:
            return 1
        if args.strict and summary["warnings"]:
            return 1
    return 0


def main_entry():
    """Console script entry point."""
    sys.exit(main())


if __name__ == "__main__":
    main_entry()
