# Open Brain — Epistemological Methodology

## 1. Epistemological Commitment

Open Brain does not claim to be correct. It claims to be falsifiable.

Every architectural assertion, quality claim, and design decision in this project is treated as a hypothesis subject to deliberate attempts at refutation. This follows Karl Popper's principle of critical rationalism: a claim that cannot, in principle, be shown to be wrong is not an empirical claim at all — it is unfalsifiable, and therefore outside the scope of engineering.

The practical consequence: when Open Brain asserts that its memory format is scale-invariant, or that its integrity layer detects tampering, or that modular code review produces better-organised findings — the assertion is accompanied by the conditions under which it would be false, and wherever possible, the methodology for testing it. The seven falsification attempts in [ARCHITECTURE.md](ARCHITECTURE.md) demonstrate this principle applied to the system's architecture. This document describes the methodology itself, provides a reproducible evaluation protocol, and identifies the boundaries of what can and cannot currently be claimed.

The commitment is not to certainty. It is to transparency about uncertainty.

---

## 2. The P-Pass Methodology

A p-pass (Popperian falsification pass) is an iterative process applied to any claim, fix, or design decision. The steps:

1. **State the claim precisely.** Vague claims cannot be falsified. "The system works well" is untestable. "The hash chain detects any single deletion or reordering of memories" is testable.

2. **Classify constraints.** Distinguish HARD constraints (physics, mathematics, cryptographic guarantees, safety — non-negotiable) from SOFT constraints (performance targets, convenience, preference — negotiable). Ambiguous constraints default to HARD until explicitly reclassified.

3. **Identify what would falsify the claim.** Name the specific observation, test result, or counterexample that would demonstrate the claim is false. If no such observation can be specified, the claim is unfalsifiable — flag it as such and do not present it as an engineering assertion.

4. **Attempt falsification.** This is iterative, not observational. Actively construct scenarios designed to break the claim. Run adversarial tests. Check edge cases. Examine the claim from the perspective of an opponent. This step distinguishes a p-pass from mere review — it requires creative hostility toward the claim being tested.

5. **Record the outcome.** Three possible results:
   - **Survives** — the claim withstood all falsification attempts. It is corroborated, not proven.
   - **Falsified** — a counterexample was found. The claim must be revised or discarded.
   - **Survives with boundary** — the claim holds within a specified scope but fails outside it. Document the boundary conditions.

6. **Document boundary conditions.** Every surviving claim has a domain of validity. State it. A hash chain that detects single deletions may not detect coordinated multi-point attacks with hash preimage computation. The boundary is part of the result.

### Monolithic vs Modular Application

A p-pass can be applied in two ways:

- **Monolithic**: a single review pass over all work product, producing one findings list. Appropriate for small, highly interdependent changes.
- **Modular**: separate per-subsystem passes, each testing the subsystem against external constraints, followed by a cross-cutting integration pass. Appropriate for larger systems with natural module boundaries.

Section 3 reports a direct comparison of these two approaches. Section 4 provides the protocol for a controlled evaluation.

---

## 3. Modular vs Monolithic — The Observation

During the Open Brain unified architecture implementation (Phases 1-5, commits `8cd1c69` through `ccfecf1`), a modular p-pass was applied: five per-module analyses (IM Store, IM CLI, Unified API, Adapters, Coordination), each tested against Genesis architectural constraints and general portability requirements, followed by full-suite testing.

**What was observed (N=1):**

- 5 per-module analyses produced approximately 20 discrete findings: 3 confirmed bugs (IMFacade metadata signature mismatch, missing FTS5 error handling, missing channel ID validation), 2 documentation defects, 2 hardening opportunities, and assessments confirming correct design for the remainder.
- Two cross-cutting constraint tables were produced: one mapping each module against Genesis architecture requirements, one verifying portability (zero OB-to-project imports, adapter registration pattern, graceful degradation).
- Per-module smoke tests (237 tests across 5 modules) ran independently before the full suite (387 tests).

**What survived falsification:**

The modular approach produced better-organised findings and more systematic constraint validation than a monolithic pass would likely produce. The cross-cutting constraint tables — which verified each module independently against external requirements — were a structural consequence of the modular decomposition. These are observable process-quality advantages.

**What did NOT survive falsification:**

The claim that modular p-passes find more bugs than monolithic passes is not supported. The three confirmed bugs were all surface-level issues (function signature mismatch, missing try/except, missing input validation) that any competent review should detect regardless of methodology. The modular approach made detection more likely through attention concentration (reviewing 90 lines in isolation vs scanning 2,300 lines), but this is an inferred cognitive effect, not a demonstrated one.

**What cannot be determined:**

Whether the improvement is real, differently biased, or noise. This is an N=1 observation without a counterfactual. The modular approach also consumed approximately 2-3 times the tokens of an equivalent monolithic pass and introduced potential inter-module blindspots (bugs spanning module boundaries are harder to see when modules are reviewed in isolation). These are genuine disadvantages that offset the structural advantages.

**The honest position:** we observed structural process improvements. We suspect modest cognitive benefits. We cannot distinguish these from noise. Section 4 provides the protocol to test this.

---

## 4. Review Methodology Evaluation Protocol

This section describes a reproducible experimental protocol for comparing modular and monolithic LLM-assisted code review. It is designed to be executable by any researcher with API access to a large language model and a codebase with known bugs.

### 4.1 Independent Variable

Two conditions:

- **Condition A (Modular):** The reviewer receives explicit module boundaries and a per-module constraint checklist. Each module is reviewed sequentially. A cross-cutting integration check follows the per-module reviews.
- **Condition B (Monolithic):** The reviewer receives the same codebase and constraint set but reviews all code in a single pass, producing one findings list with no enforced decomposition.

Both conditions use the same system prompt baseline, the same model, and the same temperature setting. The constraint set (external architectural requirements to check against) is identical.

### 4.2 Dependent Variables

| Metric | Definition | Scoring Method |
|---|---|---|
| Detection rate | Proportion of seeded bugs found | True positives / total seeded bugs |
| Precision | Proportion of findings that are real bugs | True positives / (true positives + false positives) |
| Bug-type profile | Per-category detection rate | Detection rate computed per bug category |
| Constraint coverage | Proportion of external constraints addressed | Constraints checked / total constraints in set |
| Token efficiency | Bugs found per unit of token expenditure | True positives / (tokens consumed / 1000) |
| Finding specificity | Precision of bug characterisation | 4-point rubric (Section 4.6) |
| Inter-module detection | Detection rate for cross-module bugs | Detection rate for category 5 bugs specifically |

### 4.3 Bug Taxonomy

Seven categories, derived from real defect patterns observed in software development:

| # | Category | Description | Example |
|---|---|---|---|
| 1 | Signature mismatch | Function parameter mismatch between caller and callee | `create_channel(**metadata)` vs `create_channel(metadata=dict)` |
| 2 | Missing error handling | Unhandled exception on reachable code paths | FTS5 query with malformed syntax raises unhandled `OperationalError` |
| 3 | Input validation gap | Missing validation on externally-supplied inputs | Channel ID accepts arbitrary strings without length or character checks |
| 4 | Documentation defect | Comments or docstrings that contradict code behaviour | Docstring specifies `sha256:<hex>` format; code accepts bare hex |
| 5 | Inter-module interaction | Correct in isolation, incorrect when composed | Module A returns `Optional[str]`; Module B indexes the result without null check |
| 6 | Constraint violation | Code violates an external architectural requirement | Adapter imports a project-specific type, violating the zero-coupling boundary |
| 7 | Security/safety gap | Missing bounds checks, unsigned data paths, unsafe defaults | Configuration default permits unsigned memories in a signed-memory context |

This taxonomy is sufficient for initial protocol validation but not exhaustive — categories such as concurrency defects, resource leaks, and performance regressions are absent. Researchers extending the protocol to broader codebases should extend the taxonomy accordingly, drawing from the CWE database for category definitions.

### 4.4 Corpus Construction

Take K codebases at different scales (recommended K >= 3). Open Brain itself at different git checkpoints provides natural corpus variation — each checkpoint represents a different codebase size and complexity.

For each codebase, create M bug-seeded variants (recommended M >= 5). Each variant contains a ground truth manifest listing: bug location (file, line), bug category (from Section 4.3), and bug severity (critical / major / minor).

**Seeding rules:**
- 8-15 bugs per variant, distributed across all 7 categories
- At least 2 inter-module interaction bugs per variant (category 5)
- Difficulty calibrated by pilot testing: discard bugs detected in fewer than 10% or more than 90% of pilot runs (too hard or too easy to discriminate between conditions)
- Bugs derived from real defect patterns (CWE database, real GitHub issues), not synthetic puzzles

### 4.5 Review Execution

For each bug-seeded variant, run both Condition A and Condition B.

**Controls:**
- Same model version (exact version string recorded as artifact)
- Temperature 0.0 for primary analysis (minimises non-determinism)
- Sensitivity analysis at temperature 0.3 and 0.7 (tests robustness to stochasticity)
- Same codebase content (identical bug-seeded variant)
- Same constraint set (identical external architectural requirements)

Repeat each condition N times per variant (recommended N >= 10) to account for residual LLM non-determinism.

**Artifacts to publish:**
- Exact system prompts for both conditions
- Bug-seeded codebase variants with ground truth manifests
- Raw findings from all trials
- Model version string and API configuration

### 4.6 Scoring Rubric

Each finding is evaluated against the ground truth manifest by an evaluator who has access to the manifest but is blind to which condition produced the finding.

| Criterion | Points | Description |
|---|---|---|
| Correct file | 1 | Finding identifies the file containing the seeded bug |
| Correct issue type | 1 | Finding identifies the correct category from Section 4.3 |
| Correct or partial fix | 1 | Proposed remediation addresses the actual defect |
| Fix introduces no new defects | 1 | Proposed remediation does not create a secondary bug |

**Scoring thresholds:**
- 4/4 or 3/4: true positive (full or partial detection)
- 2/4: partial detection (recorded separately in analysis)
- 1/4 or 0/4: false positive (wrong diagnosis or irrelevant finding)

**Evaluator options:** Human evaluator with SE background (gold standard) or LLM-as-judge with published rubric and human spot-checks on a random 20% sample (practical alternative). Inter-rater reliability (Cohen's kappa) should be reported if multiple evaluators are used.

### 4.7 Statistical Analysis

- Per-condition means and standard deviations for all metrics in Section 4.2
- Paired comparison: Wilcoxon signed-rank test (non-parametric) or paired t-test (if normality confirmed by Shapiro-Wilk), across all trials
- Effect size: Cohen's d with 95% confidence intervals
- Per-bug-type breakdown: detection rate by category, to test whether modular excels at specific bug types
- Token efficiency analysis: modular-to-monolithic token ratio plotted against detection rate ratio
- Minimum reportable effect size: the protocol should be powered to detect Cohen's d >= 0.5 (medium effect). With N=10 repetitions per condition per variant, this provides approximately 80% power at alpha=0.05

---

## 5. Known Limitations

Six limitations constrain the interpretation of results from this protocol:

**1. Seeded bugs are not real bugs.** Seeded defects are artificial. Real bugs emerge from developer mistakes, misunderstandings, and system complexity in ways that cannot be fully replicated by deliberate insertion. Mitigation: use realistic defect patterns derived from CWE and real issue databases. Supplementary studies on codebases with naturally-occurring bugs are encouraged.

**2. Prompt confound.** The modular and monolithic conditions necessarily use different prompts — the modular prompt specifies module boundaries and constraint checklists that the monolithic prompt omits. Any observed difference could be attributed to the prompt formulation rather than the methodology. Mitigation: publish exact prompts as experimental artifacts. Alternative prompt formulations are encouraged.

**3. Model versioning.** Results are specific to the model version tested. LLM capabilities change across versions, and a result obtained with one model may not replicate with another. Mitigation: record exact model version strings. Replication across model versions and providers is encouraged.

**4. Evaluator subjectivity.** The 4-point scoring rubric requires judgment, particularly on criterion 3 (correct or partial fix) and criterion 4 (no new defects). Mitigation: publish the rubric, use blind evaluation, and report inter-rater reliability when multiple evaluators are available.

**5. Codebase specificity.** Results obtained on Open Brain may not generalise to codebases with different architecture, language, scale, or domain. Mitigation: test across multiple codebases (K >= 3 recommended).

**6. Constraint set dependence.** The modular approach's advantage in systematic constraint checking depends on the existence of an external constraint set to check against. Codebases without explicit architectural requirements may see no benefit from modular review. This is a boundary condition of the methodology, not a limitation of the protocol.

---

## 6. Prior Art and Related Work

The protocol draws on established methodologies from software engineering and AI evaluation research:

**Mutation testing and seeded-fault studies.** Andrews, Briand, and Labiche (2005) demonstrated that carefully designed mutants can serve as valid proxies for real faults in evaluating test suite effectiveness. Just, Jalali, Inozemtseva, Ernst, Holmes, and Fraser (2014) extended this to show conditions under which mutant-based evaluation is representative. This protocol applies the same principle to LLM review evaluation rather than test suite evaluation.

**LLM-as-judge methodology.** Zheng, Chiang, Sheng, Zhuang, Wu, Zhuang, Lin, Li, Li, Xing, Zhang, Gonzalez, and Stoica (2023) established the methodology for using LLMs to evaluate LLM outputs, including position bias analysis and agreement rate measurement. This protocol's evaluator option (Section 4.6) adopts their framework with domain-specific adaptation.

**LLM-assisted code review.** Microsoft's CodeReviewer, SWE-bench (Jimenez, Yang, Wettig, Yao, Pei, Press, and Narasimhan, 2024), and SWE-agent (Yang, Jimenez, Wettig, Liber, Press, and Narasimhan, 2024) focus on LLM capability assessment (can LLMs find/fix bugs?) and model comparison (which model performs better?). The question addressed here — how to structure the review task itself — is complementary but distinct.

**Prompt decomposition.** Wei, Wang, Schuurmans, Bosma, Ichter, Xia, Chi, Le, and Zhou (2022) demonstrated that chain-of-thought prompting improves reasoning performance. Kojima, Gu, Reid, Matsuo, and Iwasawa (2022) showed that task decomposition benefits generalise across domains. This protocol tests whether the decomposition benefit applies specifically to code review methodology.

**Gap statement.** To the authors' knowledge, no published study directly compares review decomposition strategies (modular vs monolithic) for LLM-assisted code review using a controlled experimental protocol with seeded faults. [VERIFY:current — publications after May 2025 may have addressed this gap.]

---

## 7. Invitation to Falsify

This document practices what it describes. The methodology, the observation, and the evaluation protocol are all presented as falsifiable claims:

- **The methodology claim** (Section 2) — that iterative falsification produces more robust engineering outcomes than uncritical acceptance — is testable by comparing defect rates in projects that apply p-passes against those that do not.
- **The observation** (Section 3) — that modular p-passes produced structural process advantages in one instance — is honestly bounded as N=1, with disadvantages documented alongside advantages.
- **The protocol** (Section 4) — is published in full so that anyone can execute it, reproduce or refute the observation, and extend the methodology.

If the modular advantage does not replicate, that is a result, not a failure. If the protocol itself proves inadequate (insufficient statistical power, scoring rubric too subjective, seeded bugs unrepresentative), that too is a result — and the protocol should be revised. The commitment is to the process of falsification, not to any particular outcome.

Open Brain's epistemological position: provide the tools for your own refutation. If the claims survive external testing, they are strengthened. If they do not, the project is improved by the correction. Either outcome serves the goal.

---

## Further Reading

- [README.md](README.md) — what Open Brain does and how to install it
- [ARCHITECTURE.md](ARCHITECTURE.md) — scale architecture, design rationale, and architectural falsification audit
- [open_brain/README.md](open_brain/README.md) — package-level reference
