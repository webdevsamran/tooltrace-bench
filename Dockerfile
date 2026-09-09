# A runnable tooltrace-bench, offline by default.
#
# Two stages so the runtime image carries neither the build toolchain nor a git
# checkout. That second point is load-bearing here: this project shipped a wheel
# whose JSON Schemas were never packaged, and the bug stayed invisible for three
# releases precisely because every install anyone tried was an editable one with
# the repository sitting next to it. Installing a built wheel into a clean image
# is the same check `scripts/wheel_check.py` performs, enforced by the artifact
# people actually run.
#
# The image runs as a non-root user. An agent-evaluation harness executes code
# it did not write, and while the sandbox denies network at the tool layer and
# refuses paths outside the workspace, `docs/threat-model.md` is explicit that
# the local sandbox does not stop a raw-socket program spawned through `shell`.
# Container isolation is the answer to that, and it is worth nothing if the
# process is root.

# --- build ------------------------------------------------------------------
FROM python:3.12-slim AS build

WORKDIR /src
RUN python -m pip install --no-cache-dir --upgrade pip build hatchling

# Only what the wheel is built from, so an unrelated edit does not bust the layer.
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY schemas/ ./schemas/
COPY tooltrace/ ./tooltrace/

RUN python -m build --wheel --no-isolation --outdir /dist

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="tooltrace-bench" \
      org.opencontainers.image.description="Vendor-neutral, reproducible benchmarking of AI agents" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/webdevsamran/tooltrace-bench"

# git is a declared tool surface (`tooltrace/tools/process.py`), so a task that
# allows the git tool would otherwise fail for a reason that has nothing to do
# with the agent under test.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl && rm -rf /tmp/*.whl

# An unprivileged user with a writable home: sandboxes are created under a
# temporary directory, and nothing in the image needs to be writable.
RUN useradd --create-home --shell /bin/bash tooltrace
USER tooltrace
WORKDIR /home/tooltrace

# Fail the build if the installed wheel cannot load its own task packs -- the
# exact defect this image is shaped to prevent.
RUN tooltrace doctor --json > /dev/null && tooltrace tasks --json > /dev/null

ENTRYPOINT ["tooltrace"]
CMD ["--help"]
