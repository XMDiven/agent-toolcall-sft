# Phase A v2 Evidence Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved Phase A evidence repair so the data split, audit, production baseline, native Hermes reference, and reproduction metadata are independently verifiable before QLoRA begins.

**Architecture:** Keep the four-decision production JSON protocol as the only full-test-set paired baseline. Put native Hermes tool calling behind a separate runner limited to gold `tool_call` rows. Treat manifests, audit verdicts, and baseline metadata as generated evidence whose claims must be enforced by tests and whose v1 predecessors remain byte-identical.

**Tech Stack:** Python 3.11, Pydantic v2, Transformers/Qwen3 chat templates, pytest, Ruff, Git, WSL2 CUDA.

---

## File responsibility map

- `src/agent_toolcall_sft/data/safety.py`: shared fixed-format PII detection only.
- `src/agent_toolcall_sft/data/corpus.py`: canonical split hashes and all cross-split leakage gates.
- `src/agent_toolcall_sft/data/audit.py`: deterministic 60-row train/valid audit sample with complete safety-tag coverage.
- `src/agent_toolcall_sft/evaluation/prompt.py`: production four-decision JSON prompt.
- `src/agent_toolcall_sft/evaluation/native_hermes.py`: native tool definitions, prompt rendering, and gold-tool-call selection.
- `src/agent_toolcall_sft/evaluation/evidence.py`: destination reservation, hashes, Git/model/environment metadata, and read-only freezing.
- `src/agent_toolcall_sft/evaluation/run_baseline.py`: full 500-row production baseline CLI.
- `src/agent_toolcall_sft/evaluation/run_native_hermes_baseline.py`: auxiliary gold-`tool_call` baseline CLI.
- `reports/` and `data/manifests/`: versioned evidence generated only after the enforcing tests pass.

### Task 1: Preserve v1 evidence and document corrections

**Files:**
- Restore: `reports/baseline_qwen3_1_7b.md`
- Restore: `reports/data_audit_v1.md`
- Restore: `reports/data_audit_v1_sheet.md`
- Create: `reports/baseline_qwen3_1_7b_v1_errata.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Restore every v1 file from commit `8063c1b`**

Use the exact blobs from the approved-design commit and verify no v1 path differs:

```bash
git diff --exit-code 8063c1b -- \
  data/manifests/split_v1.json \
  reports/data_audit_v1.md \
  reports/data_audit_v1_sheet.md \
  reports/baseline_qwen3_1_7b.md \
  reports/baseline_qwen3_1_7b_summary.json
```

Expected: exit 0 and no output.

- [ ] **Step 2: Add a separate v1 errata**

The errata must state that v1 is immutable and superseded, distinguish the custom-envelope limitation from model behavior, and record the measured counterfactual: 64 outer-action failures, 52 Schema-valid after correcting only the outer action, 50 correct tool names, and 27 exact arguments. It must not edit a v1 file.

- [ ] **Step 3: Correct Roadmap terminology without claiming unfinished gates**

Change “same schema” to dispatch-compatible names and required argument signatures with stricter local validation. Replace scenario-family non-overlap with template-key and parameterized-pattern non-overlap. Mark local LLM rewriting as an unused optional technique. Describe the production JSON main baseline and Hermes auxiliary reference separately. Leave Phase A checkboxes open until fresh evidence exists.

- [ ] **Step 4: Verify and commit**

```bash
git diff --check
git status --short
git add ROADMAP.md reports/baseline_qwen3_1_7b.md \
  reports/data_audit_v1.md reports/data_audit_v1_sheet.md \
  reports/baseline_qwen3_1_7b_v1_errata.md
git commit -m "docs: preserve and supersede phase A v1 evidence"
git push origin main
```

Expected: v1 comparison passes; neither `AGENTS.md` nor `CLAUDE.md` is staged.

### Task 2: Enforce data safety, fingerprints, leakage, and audit coverage

**Files:**
- Create: `src/agent_toolcall_sft/data/safety.py`
- Modify: `src/agent_toolcall_sft/contracts.py`
- Modify: `src/agent_toolcall_sft/data/records.py`
- Modify: `src/agent_toolcall_sft/data/corpus.py`
- Modify: `src/agent_toolcall_sft/data/audit.py`
- Modify: `tests/test_contracts.py`
- Modify: `tests/test_records.py`
- Modify: `tests/test_corpus.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing parameterized-leakage tests**

Add a planted cross-split pair whose messages differ only by `ORD-123456` versus `ORD-654321`. Assert:

```python
report["shared_parameterized_hashes"]["train|test"] == 1
build_manifest(planted_splits, seed=20260801)["leakage_clean"] is False
```

Run in WSL:

```bash
~/.local/bin/uv run pytest tests/test_corpus.py -k parameterized -v
```

Expected RED: missing `shared_parameterized_hashes`.

- [ ] **Step 2: Implement one synthetic-parameter normalizer and gate**

Add:

```python
_SYNTHETIC_ORDER_ID = re.compile(r"ORD-\d{6}")

def normalize_synthetic_parameters(text: str) -> str:
    return _SYNTHETIC_ORDER_ID.sub("ORD-NNNNNN", text)
```

Hash `normalize(normalize_synthetic_parameters(_content(record)))`, expose every pair under `shared_parameterized_hashes`, and include it in `leakage_clean`.

- [ ] **Step 3: Write failing complete-fingerprint tests**

Independently mutate offered tools, tool order, expected decision, safety tags, and provenance. Assert every mutation changes `_split_summary(records)["sha256"]`. Assert canonical JSON uses `separators=(",", ":")`.

Run:

```bash
~/.local/bin/uv run pytest tests/test_corpus.py -k "manifest_hash or canonical" -v
```

Expected RED: at least compact canonical serialization is not implemented.

- [ ] **Step 4: Implement compact full-record fingerprints**

Serialize every complete `record.model_dump(mode="json")` with sorted keys, UTF-8 text, compact separators, and deterministic row order. Preserve list order.

- [ ] **Step 5: Write failing PII scope tests**

Parametrize phone, email, and identity-card values for `CreateSupportTicketArgs.summary`; each must fail separately. Also assert the three knowledge-tool payloads retain their dispatch-compatible non-empty string signatures and accept those strings, because only persisted support-ticket summaries receive contract-level PII rejection.

Expected RED: knowledge tools currently reject the values.

- [ ] **Step 6: Extract shared data safety and narrow contract validation**

Move `PII_PATTERNS` and `contains_pii()` into `data/safety.py`. Keep dataset-message rejection in `records.py`; apply `SafeText` only to `CreateSupportTicketArgs.summary`. Use a separate non-empty string type for knowledge tools.

- [ ] **Step 7: Write failing audit-tag coverage test**

```python
population_tags = {tag for row in auditable for tag in row.safety_tags}
sample_tags = {tag for row in sample for tag in row.safety_tags}
assert sample_tags == population_tags
```

Expected RED if any population tag is not sampled, or the sampler lacks an explicit postcondition.

- [ ] **Step 8: Enforce deterministic safety-tag coverage**

After stratified selection, deterministically replace non-essential rows with same-stratum, distinct-template candidates for missing tags. Validate size, domain/action coverage, floors, distinct template keys, and exact population-tag coverage; raise `ValueError` when impossible.

- [ ] **Step 9: Run the focused and full data suites**

```bash
~/.local/bin/uv run pytest tests/test_contracts.py tests/test_records.py \
  tests/test_corpus.py tests/test_audit.py tests/test_generation.py -v
~/.local/bin/uv run ruff check src/agent_toolcall_sft/data \
  src/agent_toolcall_sft/contracts.py tests/test_contracts.py \
  tests/test_records.py tests/test_corpus.py tests/test_audit.py
```

- [ ] **Step 10: Commit and push**

```bash
git add src/agent_toolcall_sft/data/safety.py \
  src/agent_toolcall_sft/contracts.py src/agent_toolcall_sft/data/records.py \
  src/agent_toolcall_sft/data/corpus.py src/agent_toolcall_sft/data/audit.py \
  tests/test_contracts.py tests/test_records.py tests/test_corpus.py tests/test_audit.py
git commit -m "fix: enforce phase A data evidence gates"
git push origin main
```

### Task 3: Separate protocols and freeze reproducible baseline outputs

**Files:**
- Modify: `src/agent_toolcall_sft/evaluation/prompt.py`
- Modify: `src/agent_toolcall_sft/evaluation/runner.py`
- Create: `src/agent_toolcall_sft/evaluation/native_hermes.py`
- Create: `src/agent_toolcall_sft/evaluation/evidence.py`
- Modify: `src/agent_toolcall_sft/evaluation/run_baseline.py`
- Create: `src/agent_toolcall_sft/evaluation/run_native_hermes_baseline.py`
- Modify: `src/agent_toolcall_sft/evaluation/scoring.py`
- Modify: `tests/test_evaluation.py`
- Modify: `tests/test_runner.py`
- Create: `tests/test_evidence.py`
- Create: `tests/test_native_hermes.py`

- [ ] **Step 1: Write failing protocol-separation tests**

Assert the production prompt version is `production_json_v2`, the main runner calls `apply_chat_template()` without `tools=`, and its system message contains the offered tool schemas plus all four JSON decisions. Assert the Hermes renderer passes `tools=` and `select_native_records()` returns only gold `tool_call` rows.

Expected RED: the current main runner passes native tools.

- [ ] **Step 2: Restore the production JSON main protocol**

Render the per-record offered tool schemas into the production system prompt and require exactly one four-decision JSON object. Keep parsing tolerant of native blocks for diagnostics, but do not call the main protocol “native Hermes.”

- [ ] **Step 3: Add the auxiliary Hermes protocol**

Move `build_tool_specs()` and native prompt rendering behind `native_hermes.py`. Add a runner that filters `record.expected_action == "tool_call"`, runs only that subset, and reports Schema validity, tool-name accuracy, exact/normalized arguments, off-menu rate, latency, and token counts.

- [ ] **Step 4: Write failing destination and metadata tests**

Assert an existing tag directory is rejected even if writable. Assert metadata contains Git commit, manifest and canonical test hashes, prompt/decoding versions, Python/package/GPU information, model config/tokenizer/weight hashes, and output hashes.

Expected RED: writable existing directories are currently overwritten and metadata is incomplete.

- [ ] **Step 5: Implement evidence helpers**

`reserve_destination(path)` fails whenever `path.exists()`. `hash_model_files()` hashes known model files and sorted safetensor shards. `build_reproduction_metadata()` records source coordinates. `freeze_outputs()` chmods evidence files read-only only after successful writes. Output hashes live in `metadata.json`, avoiding a self-referential summary hash.

- [ ] **Step 6: Standardize the primary metric name**

Expose `behavior_accuracy` as the strict end-to-end metric. Preserve `end_to_end_accuracy` only as a documented compatibility alias if existing reports require it; never label `action_accuracy` as behavior accuracy.

- [ ] **Step 7: Run evaluation suites**

```bash
~/.local/bin/uv run pytest tests/test_evaluation.py tests/test_runner.py \
  tests/test_evidence.py tests/test_native_hermes.py -v
~/.local/bin/uv run ruff check src/agent_toolcall_sft/evaluation \
  tests/test_evaluation.py tests/test_runner.py tests/test_evidence.py \
  tests/test_native_hermes.py
```

- [ ] **Step 8: Commit and push**

```bash
git add src/agent_toolcall_sft/evaluation tests/test_evaluation.py \
  tests/test_runner.py tests/test_evidence.py tests/test_native_hermes.py
git commit -m "eval: separate production and native baseline protocols"
git push origin main
```

### Task 4: Regenerate and audit v2 data evidence

**Files:**
- Modify: `data/manifests/split_v2.json`
- Modify: `reports/data_audit_v2.md`
- Modify: `reports/data_audit_v2_sheet.md`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Regenerate v2 splits in WSL**

```bash
~/.local/bin/uv run python -m agent_toolcall_sft.data.build
```

Expected: 2,000 train, 300 valid, 500 test; all exact, normalized, parameterized, template-key, and near-duplicate leakage gates clean.

- [ ] **Step 2: Verify the versioned manifest against generated files**

```bash
~/.local/bin/uv run pytest tests/test_corpus.py tests/test_generation.py -v
sha256sum data/manifests/split_v2.json data/processed/test.jsonl
```

Record the canonical-record hash from the manifest separately from the raw JSONL byte hash.

- [ ] **Step 3: Regenerate and complete the train/valid audit sheet**

Generate exactly 60 rows without opening the held-out test set. Review every row for label, language, offered tools, PII, and policy ambiguity. Replace each checkbox with an explicit verdict and identify the reviewer as Codex-assisted engineering review rather than claiming independent human annotation.

- [ ] **Step 4: Correct the audit report**

Remove unversioned claims about “13 checks” or reading every source phrase unless a command and output prove them. Ensure every listed known boundary still exists in the generated v2 corpus. Record limitations plainly.

- [ ] **Step 5: Commit and push data evidence**

```bash
git add data/manifests/split_v2.json reports/data_audit_v2.md \
  reports/data_audit_v2_sheet.md ROADMAP.md
git commit -m "data: freeze audited leakage-safe v2 split"
git push origin main
```

### Task 5: Re-run and freeze both baseline protocols

**Files:**
- Modify: `reports/baseline_qwen3_1_7b_v2.md`
- Create: `reports/baseline_qwen3_1_7b_native_hermes_v2.md`
- Modify: `reports/baseline_qwen3_1_7b_v2_summary.json`
- Create: `reports/baseline_qwen3_1_7b_native_hermes_v2_summary.json`
- Modify: `ROADMAP.md`

- [ ] **Step 1: Run the production JSON baseline over all 500 rows**

```bash
~/.local/bin/uv run python -m agent_toolcall_sft.evaluation.run_baseline \
  --model /home/mdiven/models/Qwen3-1.7B \
  --split data/processed/test.jsonl \
  --tag baseline_production_json_v2
```

Expected: exactly 500 predictions; no existing tag is overwritten.

- [ ] **Step 2: Run the Hermes reference over the gold-tool-call subset**

```bash
~/.local/bin/uv run python \
  -m agent_toolcall_sft.evaluation.run_native_hermes_baseline \
  --model /home/mdiven/models/Qwen3-1.7B \
  --split data/processed/test.jsonl \
  --tag baseline_native_hermes_v2
```

Expected: the selection rule and subset size are stored in metadata; no non-tool gold rows are evaluated.

- [ ] **Step 3: Verify frozen artifacts and report arithmetic**

```bash
find artifacts/baseline_production_json_v2 \
  artifacts/baseline_native_hermes_v2 -type f -maxdepth 1 -exec stat -c '%a %n' {} \;
~/.local/bin/uv run pytest -q
~/.local/bin/uv run ruff check .
```

Reports must quote generated summaries and metadata, classify 37/4-style Schema errors accurately, and state that latency is not byte-reproducible.

- [ ] **Step 4: Commit and push baseline evidence**

```bash
git add reports/baseline_qwen3_1_7b_v2.md \
  reports/baseline_qwen3_1_7b_v2_summary.json \
  reports/baseline_qwen3_1_7b_native_hermes_v2.md \
  reports/baseline_qwen3_1_7b_native_hermes_v2_summary.json ROADMAP.md
git commit -m "eval: freeze phase A v2 production and Hermes baselines"
git push origin main
```

### Task 6: Final traceability and review

**Files:**
- Modify only files required by review findings.

- [ ] **Step 1: Run complete fresh verification in WSL**

```bash
~/.local/bin/uv run pytest -q
~/.local/bin/uv run ruff check .
git diff --check
git status --short
```

- [ ] **Step 2: Verify historical and artifact invariants**

```bash
git diff --exit-code 8063c1b -- data/manifests/split_v1.json \
  reports/data_audit_v1.md reports/data_audit_v1_sheet.md \
  reports/baseline_qwen3_1_7b.md reports/baseline_qwen3_1_7b_summary.json
```

Verify all v2 report hashes against their actual files and ensure `AGENTS.md`, `CLAUDE.md`, model weights, checkpoints, secrets, and ignored artifacts are absent from every commit.

- [ ] **Step 3: Request independent code review**

Review the complete range from `e427d69` to `HEAD` against the approved design and this plan. Fix every Critical and Important issue, then rerun the full verification.

- [ ] **Step 4: Push any review-fix commit**

If review produces findings, first append a concrete repair task to this plan
with the exact affected paths and red/green command, then execute that task and
commit it as `fix: close phase A v2 review findings`. If no review fixes are
needed, do not create an empty commit.
