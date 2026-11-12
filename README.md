# woo-shipping-doctor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/woo-shipping-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/woo-shipping-doctor/issues)

A zero-dependency Python CLI that audits a WooCommerce shipping
zones CSV export for the configuration mistakes behind "no
shipping options at checkout" and wrong-rate tickets: zones
with no enabled method, duplicate zone names, regions shadowed
by an earlier zone, a catch-all zone that is not last, a
missing catch-all zone, flat rates with no cost, and free
shipping with no minimum or no condition at all.

WooCommerce matches zones top to bottom and stops at the first
match, so a specific zone below a broad one never fires, and a
customer outside every defined zone reaches checkout with no
shipping method at all. Those are the two most common shipping
configuration mistakes in WooCommerce's own troubleshooting
guide, and they are exactly what this tool catches before a
customer does.

## Install

Requires Python 3.10 or newer. No dependencies beyond the
standard library.

```bash
pip install woo-shipping-doctor
```

Or run it straight from the source checkout:

```bash
python3 woo_shipping_doctor.py examples/zones.csv
```

## Input format

A CSV export with a header row. Columns used: `zone` (zone
name), `order` (zone order, top to bottom), `regions`
(semicolon or comma separated), `method` (flat_rate,
free_shipping, or local_pickup), `enabled` (yes or no),
`cost`, `min_order` (free shipping minimum), and `requires`
(free shipping condition: none, min_amount, coupon, either,
or both). A zone spans as many rows as it has methods. A row
with a blank method registers the zone but adds no method, so
a zone with no method rows can still be audited. A UTF-8 BOM
header is handled.

```csv
zone,order,regions,method,enabled,cost,min_order,requires
United States,1,US,flat_rate,yes,9.95,,
United States,1,US,free_shipping,yes,,75.00,min_amount
California,2,US:CA,flat_rate,yes,5.00,,
Europe,3,DE;FR,flat_rate,yes,19.95,,
Europe,3,DE;FR,free_shipping,yes,,,none
Rest of the World,4,*,flat_rate,yes,,,
Antarctica,5,AQ,flat_rate,no,12.00,,
Test Zone,6,ZZZ,flat_rate,yes,abc,,
United States,7,CA,local_pickup,yes,,,
Empty Zone,8,,,,,,
```

## The zone-matching rule

WooCommerce checks zones top to bottom and uses the first
zone that matches the customer address. Source: WooCommerce
documentation, "Setting up shipping zones", and the
troubleshooting guide for core shipping
(woocommerce.com/document/troubleshooting-core-shipping):
"Shipping zones are matched top to bottom and the customer
gets the first zone that matches" and "Check for overlapping
or incomplete zip code ranges" on the zones settings page.
This tool enforces exactly that rule: a country region covers
that country and its states, a state region covers only
itself, a postcode covers only itself, and `*` covers
everything.

## What it checks

Errors, the ones that break checkout or charge the wrong rate:

* `zone-no-methods`: a zone with no enabled shipping method,
  so customers matching it see no shipping options.
* `duplicate-zone`: the same zone name at two different
  orders, so the store has the same zone twice.
* `shadowed-region`: a region already covered by an earlier
  zone, which matches first, so this zone never matches it.
* `catchall-not-last`: the catch-all zone (`*`) is not the
  last zone, so every zone below it never matches.
* `flat-rate-no-cost`: a flat rate with no cost, so checkout
  shows a zero or missing rate.
* `unparseable-cost`: a flat rate cost that is not a number.
* `negative-cost`: a flat rate cost below zero.
* `malformed-row`: a row with the wrong number of fields. The
  row is skipped and reported, never a crash.
* `missing-zone`: a row with no zone name. The row is skipped.

Warnings, hygiene issues worth fixing:

* `missing-catchall`: no zone covers `*`, so a customer
  outside every defined zone cannot check out.
* `zone-no-regions`: a zone with no regions, so it matches no
  address.
* `free-shipping-unbounded`: free shipping with no condition,
  so every order in the zone ships free.
* `free-shipping-no-minimum`: free shipping requires a minimum
  order amount but none is set, so it never triggers.
* `unparseable-min-order`: a free shipping minimum that is not
  a number.
* `unknown-method`: a method that is not a WooCommerce core
  method, so it comes from an extension.
* `unknown-requires`: a free shipping condition that is not
  one of none, min_amount, coupon, either, or both.
* `duplicate-method`: the same method twice in one zone.
* `duplicate-order`: two zones sharing one order number, so
  the match order between them is ambiguous.
* `invalid-region`: a region that is not a country code, a
  state code, a postcode pattern, or `*`.
* `invalid-order`: a zone order that is not a number, so the
  zone was placed last.

## Usage

```bash
python3 woo_shipping_doctor.py examples/zones.csv
```

Captured output:

```
ERROR [duplicate-zone] United States [order 7]: zone name 'United States' already appears at order 1, so the two zones are the same name twice
ERROR [catchall-not-last] Rest of the World [*]: the catch-all zone matches every address, so the 3 zone(s) below it never match
ERROR [shadowed-region] California [US:CA]: region is already covered by zone 'United States' (order 1), which matches first, so this zone never matches it
WARNING [free-shipping-unbounded] Europe [free_shipping]: free shipping applies to every order with no condition, so every order in this zone ships free
ERROR [flat-rate-no-cost] Rest of the World [flat_rate]: flat rate has no cost, so checkout shows a zero or missing rate
ERROR [zone-no-methods] Antarctica: zone has no enabled shipping method, so customers matching it see no shipping options at checkout
WARNING [invalid-region] Test Zone [ZZZ]: region 'ZZZ' is not a country code, a state code, a postcode pattern, or *
ERROR [unparseable-cost] Test Zone [flat_rate]: flat rate cost 'abc' is not a number
WARNING [zone-no-regions] Empty Zone: zone has no regions, so it matches no address
ERROR [zone-no-methods] Empty Zone: zone has no enabled shipping method, so customers matching it see no shipping options at checkout

Zones: 7, methods: 9, findings: 10, errors: 7, warnings: 3
```

The sample has 7 zones and 9 methods. The California zone is
dead on arrival: the United States zone above it already covers
US:CA. The Rest of the World catch-all sits at order 4 with
three zones below it, so none of them ever match. Antarctica
has only a disabled method, and Empty Zone has no methods at
all.

Use it as a CI gate: `--check` exits 1 when any error is
found, and 0 otherwise. On the sample above it exits 1:

```bash
python3 woo_shipping_doctor.py examples/zones.csv --check
```

On `examples/clean.csv`, three zones with a catch-all last, it
exits 0:

```
Zones: 3, methods: 4, findings: 0, errors: 0, warnings: 0
All zones clean.
```

With `--strict`, `--check` also fails on warnings.
`examples/warnings-only.csv` has one warning, free shipping
with no condition, so it passes `--check` (exit 0) and fails
`--check --strict` (exit 1).

`--json` emits the summary and findings as JSON, and `--out`
writes the report to a file.

## Options

| Flag | Meaning |
| --- | --- |
| `--json` | Emit JSON instead of text |
| `--check` | Exit 1 if any error is found |
| `--strict` | With --check, also exit 1 on warnings |
| `--out` | Write the report to a file |

## Edge cases

* A zone spans multiple rows, one per method, and regions are
  deduplicated per zone, so a zone with two methods over the
  same regions is not flagged as a duplicate.
* A duplicate zone name is only flagged when the second entry
  has a different order number; two rows for one zone at the
  same order are normal.
* Zones after a catch-all zone are not separately flagged as
  shadowed; the single catchall-not-last error covers them.
* A row with a blank method registers the zone and adds no
  method, so a zone with no method rows is still audited.
* A blank line in the file is skipped silently. A row with too
  many or too few fields is a malformed-row error and is
  skipped; the rest of the file is still audited.
* A region is invalid only when it matches none of the four
  forms: `*`, a two-letter country code, a state code like
  US:CA, or a postcode pattern (which must contain a digit, a
  wildcard, a dash, or a space, so a three-letter typo like
  ZZZ is caught instead of passing as a postcode).

## Tests

```bash
python3 -m unittest discover -s tests -v
```

47 tests, all passing: region parsing and coverage, the
zone-matching rule, shadowed regions, duplicate zones and
methods and orders, catch-all placement, missing catch-all,
flat rate costs, free shipping conditions, unknown methods,
invalid regions and orders, malformed rows, BOM headers,
sample counts, JSON output shape, and `--check` and `--strict`
exit codes.

## License

MIT. See [LICENSE](LICENSE).
