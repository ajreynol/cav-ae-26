# syntax=docker/dockerfile:1
#
# Dockerfile for the CAV 2026 artifact:
#   "The Cooperating Proof Calculus: Comprehensive Proofs for an SMT Solver".
#
# The image clones the latest cvc5 and ethos sources, copies the local
# benchmarks and the artifact run/build scripts into /home/user/artifact,
# builds both tools, and runs the smoke test by default.
#
# Build:
#   docker build -t cpc-cav26:1.0 .
# Interactive shell (default CMD):
#   docker run --rm -it cpc-cav26:1.0
# Run the smoke test directly:
#   docker run --rm cpc-cav26:1.0 ./run_artifact_subset.sh 10 -j 16

FROM ubuntu:24.04

# Avoid interactive tzdata/etc. prompts during apt installs.
ARG DEBIAN_FRONTEND=noninteractive

# Install build and runtime dependencies for cvc5 and ethos. This is the only
# place we run as root; everything after the USER switch below runs as `user`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ninja-build \
        ccache \
        python3 \
        python3-venv \
        python3-pip \
        python3-tomli \
        git \
        ca-certificates \
        curl \
        wget \
        libgmp-dev \
        libfl-dev \
        libtinfo-dev \
        libcln-dev \
        libedit-dev \
        libbsd-dev \
        flex \
        bison \
        gperf \
        pkg-config \
        sudo \
        time \
        procps \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Create a passwordless `user` and grant passwordless sudo so the rest of the
# image can be built without root.
RUN useradd -m -s /bin/bash user \
    && passwd -d user \
    && echo 'user ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/user \
    && chmod 0440 /etc/sudoers.d/user

USER user
WORKDIR /home/user/artifact

# Clone the latest cvc5 and ethos sources from upstream.
RUN git clone --depth 1 https://github.com/cvc5/cvc5.git  cvc5 \
 && git clone --depth 1 https://github.com/cvc5/ethos.git ethos

# Copy benchmarks, helper scripts, and run/build scripts from the artifact
# repo. material/ is intentionally not copied.
COPY --chown=user:user benchmarks/ benchmarks/
COPY --chown=user:user scripts/    scripts/
COPY --chown=user:user build_all.sh build_cvc5.sh build_ethos.sh \
                       run_artifact_subset.sh run_artifact_all_benchmarks.sh \
                       ./

# Build cvc5 and ethos as `user` using the included build scripts.
# cvc5 auto-downloads its remaining dependencies (CaDiCaL, SymFPU, ...).
RUN ./build_all.sh -j"$(nproc)"

COPY --chown=user:user README.md LICENSE ./

# Default command: drop into an interactive bash shell so reviewers can
# explore the artifact and run scripts manually.
CMD ["/bin/bash"]
