# Source Authority

Status: normative
Schema version: 2

Source authority depends on the assertion being made. There is no universal ranking, and
multiple records derived from the same underlying source are not independent corroboration.

Ordinary repository reads support orientation and scoped source inspection. Label unsupported
assertions `UNVERIFIED` with their source, bounds and consequence. A useful design draft may record
such gaps without claiming the dependent behavior is ready to implement. Absence and completeness
still require the evidence described below.

| Evidence source type       | Can establish                                                                              | Cannot establish alone                                                                 |
| -------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `org-describe`             | Accessible object/field/relation schema at observation time                                | Business meaning, closed package internals, or absence when permissions are incomplete |
| `org-tooling-enumeration`  | Accessible automation/configuration inventory when pagination and permissions are complete | Invisible package internals or vendor guarantees                                       |
| `org-soql-sample`          | Values of the bounded records observed                                                     | Universal behavior, absence, or field semantics                                        |
| `metadata-repository`      | Customer-owned intended metadata at an exact commit                                        | Deployed org state without deployment reconciliation                                   |
| `installed-package-record` | Installed package identity and version                                                     | Package behavior or supported extension points                                         |
| `vendor-documentation`     | Documented package behavior for the stated versions                                        | Current org configuration                                                              |
| `vendor-support-case`      | Vendor-confirmed behavior for the case scope and stated versions                           | Broader behavior outside that scope                                                    |
| `salesforce-documentation` | Salesforce platform semantics for the cited release/version                                | Organization policy or managed-package behavior                                        |
| `ado-approved-artifact`    | Approved requirement, design, or business intent                                           | Actual implementation or runtime behavior                                              |
| `human-sme-attestation`    | Business terminology or process meaning within the speaker's accountable scope             | Technical configuration without technical corroboration                                |
| `controlled-sandbox-test`  | Behavior under the recorded scenario, data, metadata, and package version                  | Universal behavior outside that fingerprint                                            |

Model output is not evidence. An earlier report may lead to its underlying evidence, but it
cannot provide independent corroboration of itself.

## Minimum provenance

Every evidence receipt records:

- source type and reproducible locator;
- an independence key shared by observations that come from the same underlying authority;
- observed environment and configured org key when applicable; production reads must remain within the active role's MCP permissions;
- observation and retrieval timestamps;
- collector/tool name and version;
- source revision, package version, or repository commit when applicable;
- configurable package namespace as the primary managed-package identity (with an optional local
  package key/name only as an aid);
- completeness, pagination, permissions, and missing segments;
- sensitivity classification and redactions;
- a SHA-256 digest of the sanitized observation;
- a bounded summary that contains no credentials or unnecessary record data.

Only `public` and `internal-sanitized` evidence receipts may be committed. Confidential or
restricted raw data remains outside the repository and is referenced only by a sanitized
digest/locator that an authorized reviewer can reproduce.

## Assertion-type guidance

These bounds govern what an investigation report may assert and with how much confidence:

- Schema, ownership, relation, and automation assertions require a complete technical source in
  the matching org scope. Repository metadata is corroborating evidence unless deployed state is
  also reconciled.
- Runtime-behavior assertions require a controlled test or multiple applicable observations. One
  SOQL sample remains an observation, not a universal fact.
- Package limitations require vendor evidence tied to package version, or remain a scoped observed
  behavior rather than a vendor rule.
- Business meaning and process assertions require a named accountable SME or approved artifact;
  technical metadata cannot establish semantics by itself.
- Absence assertions require complete enumeration and permission proof, and expire fastest.
