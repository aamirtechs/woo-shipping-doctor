# Good first issues

Seeded issues for new contributors. File each one on GitHub with
the `good first issue` and `help wanted` labels.

## 1. Add a per-zone coverage table

Title: Show which countries each zone actually matches

Description: After the findings, print a short table of each
zone with its order and the regions it matches (expanding a
country region to the country itself, and noting that a state
region matches only that state), so a store owner can see at a
glance which zone a customer in a given country lands in.

Difficulty: Easy

Acceptance criteria: the table appears in text output with the
correct rows for the sample file (United States first, Rest of
the World last with *); JSON output is unchanged; a test checks
the table rows.

## 2. Add a --suggest-order flag

Title: Suggest a zone order that removes all shadowing

Description: Add a --suggest-order flag that prints the zones
sorted most specific first (state regions before country
regions, country regions before the catch-all), so a store
owner can reorder the zones in WooCommerce and clear every
shadowed-region finding in one pass. The tool itself must never
change anything in the store.

Difficulty: Easy

Acceptance criteria: the suggestion for the sample file puts
California above United States and Rest of the World last; a
test checks the suggested order; README documents the flag.

## 3. Support shipping classes in flat rate costs

Title: Audit flat rate costs per shipping class

Description: WooCommerce flat rates can carry a cost per
shipping class. Add an optional --classes file (class name,
one per line) and a `class_costs` column (class:cost pairs
separated by semicolons), and flag a flat rate that names a
class not in the file, or a class cost that is blank or not a
number, with the same error rules as the main cost.

Difficulty: Medium

Acceptance criteria: a sample row with an unknown class is
flagged; a row with a valid class cost passes; a test covers
both cases; README documents the column and the flag.

## 4. Add a zone method coverage report

Title: Report which methods each zone is missing

Description: Add a --coverage flag that prints, after the
summary, a table of zones against the three core methods
(flat_rate, free_shipping, local_pickup) with a yes or no per
cell, so a store owner can see which zones lack a free shipping
option or a local pickup option without reading every finding.

Difficulty: Easy

Acceptance criteria: the table for the sample file shows
Antarctica and Empty Zone with no methods at all; a test
checks the table rows; README documents the flag.
