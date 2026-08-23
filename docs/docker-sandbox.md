# Docker Verification Sandbox

## Purpose

RepoPilot can execute its allowlisted verification command either directly on the host or in an
ephemeral Docker container. Docker mode reduces the authority of repository-controlled test code;
it does not make arbitrary code safe or replace the existing command and path policies.

## Build and use

```bash
docker build --tag repopilot-sandbox:py312 docker
export OPENAI_API_KEY="your-key"
repopilot run \
  --execution-backend docker \
  --local-repo /path/to/repository \
  --task "Make the requested scoped change." \
  --verify pytest -q
```

RepoPilot never pulls an image implicitly. Override the reference image with `--docker-image` or
`REPOPILOT_DOCKER_IMAGE` when a repository needs additional preinstalled dependencies.

## Enforced controls

- The verification argv passes the same allowlist and path checks as local execution.
- The Docker CLI and container command receive argument vectors without a shell.
- Container networking is `none`, and implicit image pulls are disabled.
- The copied repository is mounted read-only at `/workspace`.
- The container root filesystem is read-only; `/tmp` is a bounded writable tmpfs.
- Linux capabilities are dropped and `no-new-privileges` is enabled.
- CPU, memory, PID, command-output, and wall-clock limits are bounded.
- On POSIX hosts, the container uses the invoking user's numeric UID and GID.
- A timeout or interrupted Docker client triggers forced removal of the named container.
- Provider credentials and the broader host environment are not passed into the container.

## Limits and residual risk

- Containers share the host kernel. Kernel or Docker Engine vulnerabilities remain out of scope.
- Access to the Docker daemon is itself privileged; RepoPilot does not expose its socket inside the
  container, but it relies on the installed client and daemon.
- Image contents and registries are supply-chain trust decisions. Build and audit custom images
  before selecting them. The reference image's upstream base tag is mutable and should be pinned by
  digest in a production release process.
- Resource enforcement varies by Docker Engine and host platform, especially Docker Desktop.
- Read-only repositories can break suites that insist on writing build products beside source.
  Configure those tools to use `/tmp` or provide a purpose-built image and command.
- Network-disabled runs cannot download dependencies. Required dependencies must already exist in
  the selected image or repository checkout.
- Docker mode protects only verification commands. RepoPilot's own file and Git tools continue to
  operate on the disposable host-side copy under application policy.
- The default automated suite validates command construction and failure handling with an injected
  process runner. Set `REPOPILOT_RUN_DOCKER_TESTS=1` to include the live isolation integration test
  on a Docker-enabled host.

## Configuration

The defaults are one CPU, 512 MiB memory, 128 processes, a 256 MiB tmpfs, and the existing command
timeout. Bounds can be adjusted with `REPOPILOT_DOCKER_CPUS`, `REPOPILOT_DOCKER_MEMORY_MB`,
`REPOPILOT_DOCKER_PIDS_LIMIT`, and `REPOPILOT_DOCKER_TMPFS_MB`.
