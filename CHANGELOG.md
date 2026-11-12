# Changelog

## 1.0.0 - 2026-11-10

Initial release.

* Shipping zone audit over a WooCommerce zones CSV export:
  zones with no enabled shipping method, duplicate zone names,
  regions shadowed by an earlier zone, a catch-all zone that is
  not last, a missing catch-all zone, flat rates with no cost,
  unparseable or negative costs, free shipping with no minimum
  or no condition at all, duplicate methods and duplicate zone
  orders, unknown methods, and invalid regions.
* WooCommerce zone-matching rule enforced as the shadowed-region
  error: zones match top to bottom and the first match wins, so
  a country region covers that country and its states, a state
  region covers only itself, a postcode covers only itself, and
  * covers everything (WooCommerce documentation, "Setting up
  shipping zones", and the core shipping troubleshooting guide).
* Malformed CSV rows and rows with no zone name are reported as
  data errors and skipped, never a crash. UTF-8 BOM headers and
  extra columns handled. Regions accept semicolon or comma
  separators.
* Findings carry a zone, a detail, a rule name, a severity
  (error or warning), and a message; errors and warnings are
  counted in the summary.
* Text and --json output, --out file output, and a --check CI
  gate that exits 1 on errors (and on warnings with --strict).
* Zero dependencies, Python 3.10 or newer.
