CAV 2026 Artifact
=======================================

Paper title: The Cooperating Proof Calculus: Comprehensive Proofs for an SMT Solver

Claimed badges: Available + Reusable

Justification for the badges:

  * Functional: The artifact reproduces the experimental workflow from
    Section 5 of the paper. It includes the source trees of both `cvc5`
    (`./cvc5/`) and `ethos` (`./ethos/`), build scripts, benchmark-running
    scripts, and scripts for generating the final summary tables. The CPC
    proof calculus used by the artifact is included in
    `./cvc5/proofs/eo/cpc/Cpc.eo`.

    - replicated:
      * Table 1: point (1) of FULL REVIEW, produced as
        `./data/M/summary-table.md` for a subset run and `./data/0/summary-table.md`
        for the all-benchmarks run.
      * Table 2: point (2) of FULL REVIEW, produced as
        `./data/M/rule-counts.csv` for a subset run and `./data/0/rule-counts.csv`
        for the all-benchmarks run.

    - not-replicated:
      * The verification claims from Section 4 are not evaluated separately as
        a standalone artifact task; the artifact focuses on reproducing the
        Section 5 experimental results.

  * Reusable: The artifact includes the source code of the main solver and
    checker, local build scripts, benchmark-running scripts, and output
    summarization scripts. The workflow can be rerun with different sample
    sizes, timeouts, numbers of jobs, and optional proof deletion, which makes
    the artifact usable beyond the exact paper run.

Requirements:

  * RAM: 128 GB recommended
  * CPU cores: 16 cores recommended
  * Time (smoke test): approximately 30-90 minutes on a 16-core machine for
    `./run_artifact_subset.sh 10 -j 16`
  * Time (full review): approximately 6-12 hours on a 16-core machine for
    `./run_artifact_subset.sh 500 -j 16 --timeout 600 --delete-proofs`;
    the complete all-benchmarks run can take multiple days

external connectivity: NO

  The artifact package contains prebuilt `cvc5` and `ethos` binaries. If they
  are not available, the scripts rebuild them from the included source trees
  without requiring network access.

-------------------------------------------------------------------------------
**                                SMOKE TEST                                 **
-------------------------------------------------------------------------------

Download the artifact package on the virtual machine into the `$HOME`
directory, extract it, and run the following from the artifact root:

  `./run_artifact_subset.sh 10 -j 16`

This command samples 10 benchmarks from each of the six benchmark categories
(`QF+UF`, `QF+Arith`, `QF+BV`, `QF+Str`, `Q+UF`, `Q-UF`), for 60 benchmarks in
total.

For each benchmark, the workflow runs:

  * `cvc5` with base options
  * `cvc5` with proof checking
  * `cvc5` with proof dumping
  * `ethos` on the dumped proof
  * `cvc5` with proof checking and internal statistics

The base cvc5 options are:

  `--enum-inst --safe-mode=safe`

The default per-benchmark timeout is 60 seconds.

Raw outputs are written to:

  `./output/10/`

Summaries are written to:

  * `./data/10/summary.csv`
  * `./data/10/rule-counts.csv`
  * `./data/10/summary-table.md`

The scripts print progress as they execute benchmarks.

(1) To check that Table 1 generation works, open:

  `./data/10/summary-table.md`

The file should contain a Markdown table with one row for each of the six
benchmark categories and one final `Overall` row. Concrete times and timeout
counts may vary across machines, but the file should be well-formed and should
summarize solve, proof, check, ratio, and proof-size information.

(2) To check that Table 2 generation works, open:

  `./data/10/rule-counts.csv`

The file should contain the header:

  `rule,count`

and then a list of proof rules sorted by descending frequency.

For completeness, the raw outputs for the smoke test are stored under
`./output/10/`. Each benchmark directory contains:

  * `cvc5-solve.txt`
  * `cvc5-solve-proof.txt`
  * `cvc5-proof-gen.txt` unless `--delete-proofs` is used
  * `cvc5-solve-proofs-stats.txt`
  * `ethos-check.txt`

Note that some timeouts are expected, especially on proof-enabled runs and in
less stable logics such as `QF_NIA` and `QF_BV`. This is normal.

-------------------------------------------------------------------------------
**                               FULL REVIEW                                 **
-------------------------------------------------------------------------------

Assuming the smoke test passed, we recommend the following representative run:

  `./run_artifact_subset.sh 500 -j 16 --timeout 600 --delete-proofs`

This runs 500 benchmarks per category and is intended to reproduce the same
overall trends as the paper while remaining much cheaper than the full
all-benchmarks run.

The outputs will be:

  * raw benchmark outputs in `./output/500/`
  * benchmark summary CSV in `./data/500/summary.csv`
  * proof-rule summary CSV in `./data/500/rule-counts.csv`
  * Markdown summary table in `./data/500/summary-table.md`

In the following outputs, exact values may differ across machines, but the
overall trends should stay similar.

(1) To obtain the results corresponding to Table 1, inspect:

  `./data/500/summary-table.md`

This file is the artifact’s reproduction of the category-wise summary table
from the paper.

(2) To obtain the results corresponding to Table 2, inspect:

  `./data/500/rule-counts.csv`

This file aggregates proof-rule counts across all benchmarks in the run and is
the artifact’s reproduction of the proof-rule frequency table from the paper.

For a complete run of all benchmarks in the artifact, use:

  `./run_artifact_all_benchmarks.sh`

This script takes no arguments. It internally runs all benchmarks with a
600-second timeout and deletes dumped proofs after the Ethos check to keep disk
usage manageable. The outputs of this complete run are written to:

  * `./output/0/`
  * `./data/0/summary.csv`
  * `./data/0/rule-counts.csv`
  * `./data/0/summary-table.md`

Additional command-line options are available via:

  * `./run_artifact_subset.sh --help`
  * `./run_artifact_all.sh --help`
  * `./scripts/run_artifact_subset.py --help`
