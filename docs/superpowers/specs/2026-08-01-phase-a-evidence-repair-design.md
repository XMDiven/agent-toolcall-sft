# Phase A Evidence Repair Design

## 1. Goal

Repair the Phase A data, safety-contract, evaluation, and evidence defects before
QLoRA work begins. The repaired evidence becomes version 2. Version 1 remains
immutable historical evidence and is explicitly marked as superseded rather
than overwritten.

The repair is complete only when:

- parameterized sentence patterns do not cross train, valid, and test;
- each split hash covers the complete canonical dataset records;
- support-ticket decisions containing fixed-format PII fail closed;
- action accuracy and end-to-end behavior accuracy are distinct metrics;
- the production JSON baseline and native Hermes reference baseline are named
  and interpreted according to their actual protocols;
- version 2 audit, manifest, baseline, and reproduction metadata are traceable;
- the repository test suite and Ruff pass in the supported WSL environment.

## 2. Versioning and Preservation

The existing version 1 files and ignored artifacts are not modified:

- `data/manifests/split_v1.json`
- `reports/data_audit_v1.md`
- `reports/data_audit_v1_sheet.md`
- `reports/baseline_qwen3_1_7b.md`
- `reports/baseline_qwen3_1_7b_summary.json`
- `artifacts/baseline/`

The repair creates version 2 outputs:

- `data/manifests/split_v2.json`
- `data/processed/{train,valid,test}.jsonl` regenerated locally from v2 rules;
- `reports/data_audit_v2.md`
- `reports/data_audit_v2_sheet.md`
- `reports/baseline_qwen3_1_7b_v2.md`
- `reports/baseline_qwen3_1_7b_v2_summary.json`
- `reports/baseline_qwen3_1_7b_v1_errata.md`
- `artifacts/baseline_v2/`
- `artifacts/baseline_native_hermes_v2/`

The ignored `data/processed/` paths may be replaced by regenerated v2 files
because the versioned manifest is their source of truth. Frozen v1 artifacts
remain read-only.

## 3. Data Leakage Repair

### 3.1 Root cause

`order_status_lookup` generates a random synthetic order ID but does not set a
stable `template_key`. `generate_family()` therefore substitutes the unique
record ID. Records built from the same sentence pattern can be assigned to
different splits because each row appears to be its own template.

Existing exact, punctuation-normalized, and shingle checks retain the random
order ID. The differing digits hide the shared parameterized pattern.

### 3.2 Stable parameterized template identity

Add one deterministic normalization function for synthetic parameters. Version
2 initially recognizes the project's synthetic order IDs matching
`ORD-\d{6}` and replaces them with `ORD-NNNNNN`.

`order_status_lookup` derives its `template_key` from the fully rendered user
message after synthetic-parameter replacement. This keeps equal parameterized
expressions together while retaining enough groups for exact 2,000/300/500
split sizes. Other families keep their existing explicitly assigned keys.

### 3.3 Defense in depth

The leakage report adds `shared_parameterized_hashes`, calculated after both
synthetic-parameter replacement and existing text normalization. Any non-zero
cross-split intersection makes `leakage_clean` false. A planted pair with only
different order IDs must be detected by a regression test.

The manifest continues reporting shared `scenario_family` values for
transparency, but scenario-family overlap is not treated as leakage. The split
unit is `template_key`, as documented in the Roadmap.

## 4. Complete Dataset Fingerprints

The split fingerprint is the SHA-256 of newline-separated canonical JSON
records in their deterministic split order. Canonical serialization uses the
complete `DatasetRecord` JSON representation with sorted object keys and
compact separators. List order is preserved because message order and offered
tool order affect the model prompt.

Consequently, changing any of the following changes the split hash:

- messages or record identity;
- template key, scenario family, or domain;
- offered tool list or its order;
- expected action or complete expected decision;
- safety tags;
- generator, template version, or seed.

The manifest file itself also receives a SHA-256 in the baseline reproduction
metadata. Tests mutate tools, labels, and safety tags independently and assert
that each mutation changes the split fingerprint.

## 5. Shared PII Safety Validation

Move fixed-format PII detection into a focused data-safety module so contracts
and dataset records use the same implementation without circular imports.

The shared detector covers the existing supported patterns:

- mainland China mobile numbers;
- email addresses;
- mainland China identity-card numbers.

`DatasetRecord.messages` retains its current rejection behavior.
`CreateSupportTicketArgs.summary` adds a field validator that rejects a summary
when the shared detector matches. Names and physical addresses remain manual
audit concerns because reliable regular-expression validation is not available.

The contract remains stricter than `rag-agent-platform`: the three knowledge
tools have identical names and required argument names, while this project also
rejects extra fields and empty strings. The Roadmap describes this as
dispatch-compatible signatures rather than byte-identical JSON Schema.

## 6. Evaluation Metric Semantics

Keep the existing `action_accuracy` and label it accurately as four-way action
classification accuracy.

Add `behavior_accuracy` as the primary end-to-end correctness metric:

- for `clarify`, `direct_answer`, and `handoff`, the predicted action must match;
- for `tool_call`, the action, tool name, and complete arguments must match;
- an unparseable or Schema-invalid output is incorrect and remains in the
  denominator.

Free-form question, answer, and handoff wording is not compared verbatim. The
dataset specifies the required decision class, whereas semantically equivalent
natural-language phrasing is not reliably measured by exact string equality.

The existing tool-name and argument metrics remain diagnostic secondary
metrics. Reports no longer call `action_accuracy` "overall behavior accuracy."

Schema-error taxonomy is explicitly a taxonomy of the first reported Pydantic
error, not proof that no secondary error exists. The v1 errata recomputes the
counterfactual envelope analysis from frozen predictions and records that only
52 of 64 envelope-tag failures become Schema-valid after changing the outer
action.

## 7. Baseline Protocols

### 7.1 Primary production JSON baseline

The primary paired baseline keeps the four-decision JSON protocol used by the
future `/v1/route` API. It evaluates all 500 v2 test records and is the only
baseline used for the later base-versus-Adapter paired confidence interval.

Documentation calls it the production JSON decision protocol. It does not call
it Qwen's native Hermes function-calling protocol. The prompt version receives
an explicit production-oriented version name so report readers cannot confuse
the two protocols.

### 7.2 Auxiliary native Hermes reference

An auxiliary runner passes native function definitions through the tokenizer's
`tools=` argument and parses Qwen's `<tool_call>` output. It evaluates only v2
records whose expected action is `tool_call`, because native Hermes has no
equivalent representation for this project's `clarify` and `handoff` decision
classes.

The auxiliary report includes:

- evaluated subset size and selection rule;
- tool-name accuracy;
- argument exact match and normalized match;
- tool Schema validity;
- off-menu call rate;
- latency and token counts.

It is a fairness reference for the base model's native tool-routing ability. It
is not mixed into the main behavior-accuracy claim and is not compared directly
with the Adapter unless the Adapter is separately trained for native Hermes.

## 8. Reproduction Metadata

Version 2 baseline metadata records:

- Git commit;
- complete manifest file SHA-256;
- v2 test split canonical-record SHA-256;
- model source path or identifier;
- hashes for model weight shards, model configuration, generation
  configuration, tokenizer configuration, tokenizer JSON, and safetensors
  index when present;
- prompt and decoding versions;
- Python package versions, PyTorch version, GPU name, and peak VRAM;
- raw prediction and summary hashes.

Reproduction commands always write to a new tag such as `baseline_v2_repro`.
They never target a frozen directory. Output equivalence is checked on raw
model completions and deterministic metrics; latency bytes are not expected to
match across runs.

## 9. Audit and Roadmap Evidence

The v2 audit sample remains limited to train and valid. It preserves the
knowledge and high-risk floors, covers both domains and all four actions, and
adds a deterministic postcondition that every safety tag present in the audit
population appears at least once in the 60-row sample.

The completed v2 sheet records a verdict for each row. Problems are categorized
as label, template, drift, or policy. Rule defects cause full regeneration; test
answers are never edited individually.

Roadmap changes:

- replace the obsolete scenario-family split checkbox with the actual
  template-key rule;
- add parameter-normalized leakage and full-record fingerprint requirements;
- mark LLM rewriting as an unused optional technique rather than an unfinished
  gate;
- describe the main production JSON baseline and auxiliary Hermes reference;
- distinguish action accuracy from end-to-end behavior accuracy;
- replace "same JSON Schema" with dispatch-compatible name and required-
  argument signatures plus stricter local validation;
- mark v1 evidence as superseded and require v2 evidence before Phase B.

## 10. Test and Execution Sequence

Every production change follows red-green-refactor independently:

1. reproduce parameterized leakage with a failing corpus test;
2. add the stable order-status key and parameterized leakage gate;
3. prove metadata and label mutations do not currently change the hash, then
   replace the fingerprint implementation;
4. prove ticket summaries with each supported PII type are accepted, then add
   shared fail-closed validation;
5. prove wrong tool calls currently receive action credit, then add
   `behavior_accuracy` without changing `action_accuracy`;
6. add protocol-specific prompt and parser tests before auxiliary Hermes code;
7. add metadata and non-overwrite tests before changing the baseline runner;
8. run focused tests, the complete WSL test suite, and Ruff;
9. regenerate v2 data and verify all manifest gates;
10. complete the v2 train/valid audit;
11. run the primary GPU baseline into a new directory;
12. run the auxiliary native Hermes reference into another new directory;
13. verify hashes, reports, read-only permissions, and a clean Git status.

No QLoRA configuration or training starts until all version 2 Phase A gates are
complete.

## 11. Risks and Trade-offs

- The v2 split changes which records are held out, so v1 and v2 baseline metrics
  are not directly comparable. Reports state this explicitly.
- Parameterized message keys are stronger than unique record keys but less
  strict than holding out entire scenario families. This preserves evaluation
  of routing within known scenario types while blocking memorized sentence
  skeletons.
- The production JSON baseline may understate Qwen's native function-calling
  ability. The auxiliary Hermes reference makes that limitation measurable
  without weakening the production-contract comparison.
- PII regular expressions cannot reliably identify names and physical
  addresses. Manual audit remains necessary.
- Complete-record hashes intentionally change when tool-list order changes,
  because that order can change prompts and model outputs.
