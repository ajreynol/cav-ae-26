This directory contains the supplemental material for the CAV 2026 submission "The Cooperating Proof Calculus: Comprensive Proofs for an SMT Solver". It contains three subdirectories:

First, the directory ./cpc/ contains the complete definition of the Cooperating Proof Calculus (CPC), which is approximately 6400 lines of Eunoia. It contains subdirectories for the programs, rules, and theory definitions that CPC is based on. It can be parsed by the Ethos proof checker (see https://github.com/cvc5/ethos/blob/main/user_manual.md for details).

Second, the directory ./smt_vc/ contains 571 *.smt2 files corresponding to the correctness of CPC rules. In particular, these verification conditions conjecture that there exists an input to the proof rule where the premises are satisfied but the conclusion is not, where this is expected to be unsatisfiable. The verification conditions themselves are contained in the subdirectory ./smt_vc/vc/, and the results of cvc5 and z3 on these benchmarks is given in ./smt_vc/results/.

Third, the directory ./evaluation/ contains a CSV corresponding to the results of the evaluation, which was run on all SMT-LIB logics without floating points. We additional provide a file, ./evaluation/stats-proof-rule-counts.txt giving a total number of times each proof rule in CPC was used in this evaluation.
