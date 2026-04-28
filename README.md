CAV 2026 Artifact
=======================================
Paper title: The Cooperating Proof Calculus: Comprehensive Proofs for an SMT Solver

Claimed badges: Available + Functional + Reusable

Justification for the badges: [no need to justify Available -- just provide the DOI link in HotCRP]

  * Functional: This artifact provides a way of reproducing the evaluation
    run in Section 5 of the paper. We provide both the source code of the
    SMT solver cvc5 (./cvc5/) and the proof checker ethos (./ethos/). The proof
    calculus CPC, as introduced by this paper is available within cvc5's
    code base (./cvc5/proofs/eo/cpc/Cpc.eo), which the ethos checker uses as
    the basis for checking cvc5 proofs.

    - replicated: Table 1 is reproduced using the script `./run_artifact_all.sh`
      or `./run_artifact_subset.sh`, in output `./data/M/summary_table.md`
      (see below for details).
    
    - replicated: Table 2 is also reproduced using the script 
      `./run_artifact_all.sh` or `./run_artifact_subset.sh`, in output
      `./data/M/rule-counts.csv`.

    - not-replicated: The verification claims in Section 4 are out of
    scope of this artifact.

  * Reusable: Both cvc5 and ethos have extensive regression tests and are
    publicly available. cvc5's regression tests run with ethos proof checking
    of CPC proofs (command `make regress-cpc`). cvc5 by default builds with a
    modified BSD 3 license; ethos uses a similar modified BSD 3 license.

Requirements:

  * RAM: 128 GB (recommended)
  * CPU cores: 16 cores (recommended)
  * Time (smoke test): Variable; the run script can be given a number of runs.
  * Time (full review): ???

external connectivity: NO

  The artifact contains prebuilt binaries of cvc5 and ethos.

-------------------------------------------------------------------------------
**                                SMOKE TEST                                 **
-------------------------------------------------------------------------------

Download the artifact package on the virtual machine into the $HOME directory
and run the following:

  `cd artifact/`
  `./run_artifact_subset.sh 10 -j N`
  
where N is the number of cores to use. The value of 10 can be varied, we
recommend starting with 10 in the smoke test.

The artifact has 153,188 benchmarks from SMT-LIB in the `./benchmarks/`
subdirectory, which are unsat benchmarks taken from all SMT-LIB logics (apart
from floating point logics) that a reference version of cvc5 solved within a 60
second timeout.

The script `./run_artifact_subset.sh M -j N` will perform the following:
1. Randomly choose M benchmarks from each category in Table 1 (QF+UF, QF+Arith,
   QF+BV, QF+Str, Q+UF, Q-UF).
2. For each of these benchmarks:
   a. Solve the benchmark with cvc5,
   b. Solve the benchmark with cvc5 and internal proof checking,
   c. Solve the benchmark with cvc5 and print the proof to file,
   d. Check the proof generated in step c with ethos,
   e. Run cvc5 with internal proof checking and statistics enabled.
   Each of these raw outputs is stored in the output directory `./output/M/`,
   along with timing information.
3. We parse the results of the raw output into a CSV, stored in 
   `./data/M/

Note that some benchmarks may timeout (roughly 0.6 percent of benchmarks on
step 2b and roughly 1.1 percent of benchmarks on step 2c,d). Expect to see
some timeouts, especially in logics where cvc5 is unstable such as QF_NIA
and QF_BV.

To keep the evaluation brief, `./run_artifact_subset.sh` uses a timeout of 60
seconds by default, but a 600 second timeout was used in the paper
for steps 2b and 2c,d.

The script will report its progress and report its data in the end:
- `./data/M/summary_table.md` which contains a markdown version of Table 1
from the paper.
-  `./data/M/rule-counts.csv` which contains a CSV of rules used in proofs
in the previous run, which should be similar to Table 2 from the Appendix.
   
*** A further note about timeouts and reproducibility:

Note that the 153,188 benchmarks coincide with the same benchmarks considered
in the paper. The selection criteria was to pick all benchmarks that cvc5
could solve within a 60 second timeout on the machinery mentioned in the paper.
Since cvc5 can vary slightly based on the platform, it may be possible that
the results vary in this artifact, which is why the results may not reproduce
exactly, and e.g. the cvc5 solve column may contain timeouts.

Running `./run_artifact_subset.sh -h` additionally shows helpful outputs for
the evaluation. In particular, for large runs, we recommend using
`--delete-proofs` to ensure the raw output does not cause memory issues.

-------------------------------------------------------------------------------
**                               FULL REVIEW                                 **
-------------------------------------------------------------------------------

A full review should run a larger subset of the above script,
we recommend:

  `cd artifact/`
  `./run_artifact_subset.sh 500 -j N`

which will run 500 benchmarks per category.

Alternatively, for a complete run of the experiments, the script
`./run_artifact_all.sh -j N` be used. However, this will take quite a long
time to complete on a single machine.
