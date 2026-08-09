# SpecLedger Architecture

## Product boundary

SpecLedger is a product-data trust and change-impact layer. It is not intended to replace an ERP, PIM, PLM, or eCommerce platform in the hackathon prototype.

## Core concepts

### Product

The catalog item being described, identified by a stable SKU or manufacturer part number.

### Attribute

A product property such as pressure rating, voltage, material, size, or temperature range.

### Evidence

The source supporting an attribute: a document, page, URL, row, or user-provided record.

### Product version

A time-stamped snapshot of a product's attributes. Versions are retained so that changes can be reviewed instead of silently replacing history.

### Conflict

Two sources or versions provide different values for the same attribute.

### Impact relationship

A connection between records that may be affected by a change, such as a product listing, variant, accessory, or compatibility relationship.

## Trust model

Every value has a status:

- `verified`: directly supported by an accepted source;
- `inferred`: suggested by a model or transformation;
- `conflict`: disagrees with another source;
- `missing`: required but unavailable;
- `review_required`: needs a human decision.

The backend will enforce these statuses. The future UI will make them visible.

## Build sequence

1. Typed product and evidence models.
2. Deterministic validation.
3. Local persistence.
4. Version comparison and conflict detection.
5. PDF extraction with evidence references.
6. Impact relationships and analysis.
7. Review dashboard.
8. Optional AI enrichment with explicit provenance.

## Why this sequence matters

If extraction or AI is added first, it becomes difficult to tell whether a result is correct. The trust model and tests must exist before intelligent automation is introduced.

