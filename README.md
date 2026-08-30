# Colima / Dev Env Images

Docker images for the local development environment, served through
[Colima](https://github.com/abiosoft/colima) as a lightweight Docker
daemon replacement on macOS / Linux.

## Requirements

- [Colima](https://github.com/abiosoft/colima) (provides the Docker daemon)
- `docker` CLI on PATH (Colima wires this up for you)
- Make

Install Colima and Docker:

```bash
brew install colima docker
```

## Repository layout

```
.
├── images/        # Per-image build directories (each has a Dockerfile)
│   └── <name>/Dockerfile
├── compose.yaml   # Local dev stack wiring the images together
├── .env.example   # Template for compose settings (copy to .env)
├── workspace/     # Host directory mounted into the containers
└── Makefile       # Helpers to build/push images and drive compose
```

Each subfolder under `images/` is a standalone image, identified by its
folder name. A folder is only treated as an image if it contains a
`Dockerfile`.

## Usage

Run `make` (or `make help`) to list every target.

### Environment (Colima)

```bash
make up        # start the Colima VM / docker daemon
make down      # stop it
make status    # show its state
make restart   # restart it
```

### Images

```bash
make list                          # list available image names
make build NAME=<name>             # build a single image
make build-all                     # build every image in images/
make push NAME=<name>             # push a single image to a registry
make push-all                      # push every image
make run NAME=<name>            # run an image interactively
make shell NAME=<name>          # drop into a shell in a built image
```

### Cleanup

```bash
make prune    # remove dangling images and unused resources
make clean    # remove all containers and dangling images
```

### Options

| Variable   | Default     | Description                          |
|------------|-------------|--------------------------------------|
| `NAME`     | —           | Image folder name under `images/`    |
| `REGISTRY` | `ghcr.io`   | Target registry for `push`           |
| `TAG`      | `latest`    | Image tag                            |

```bash
make push NAME=opencode REGISTRY=ghcr.io/<you> TAG=v1.0.0
```

## The `opencode` image

A minimal, pinned image that runs [opencode](https://opencode.ai) in
serve mode on port `4096`.

- Base: `debian:bookworm-slim`, non-root user `opencode` (uid `10001`).
- Fetches the pinned release binary from GitHub and verifies the embedded
  version before placing it on `PATH` — no `curl | bash`.
- Multi-arch: picks the `x64` or `arm64` asset to match the build host.
- Exposes `4096` with a healthcheck against `/global/health`.

Pin or override the version at build time:

```bash
make build NAME=opencode
# or, pin a specific release:
docker build --build-arg OPENCODE_VERSION=1.18.25 -t opencode:latest images/opencode
```

Run it:

```bash
make run NAME=opencode
# → opencode serve --hostname 0.0.0.0 --port 4096
```

## The `opencode-global` image

The `opencode` image with the **global opencode config baked in**: one central
provider and a shared set of agents, so that *any* container started from this
image boots with every agent already loaded. It is meant to be **loaded** and
used as a base for your opencode instances.

- Built **on top of** `opencode:latest` (`FROM opencode:latest`): same pinned
  binary, same non-root user `opencode` (uid `10001`), same `/work`, same
  healthcheck, same multi-arch behaviour — it only layers the config, it does not
  re-download or re-verify the binary.
- Layout `images/opencode-global/`: a `Dockerfile`, a `.dockerignore`, and a
  `config/` subfolder that is a **mirror** of the `opencode-global/` directory
  (sibling of `AI`, e.g. `~/OpenCode/opencode-global/`).

### Where the config lands in the container

opencode reads its global config from `XDG_CONFIG_HOME` (`$HOME/.config`). The
baked location is `/home/opencode/.config/opencode/`:

- `opencode.json` — provider `ollama-remote` → `http://192.168.2.40:11434/v1`,
  base `@ai-sdk/openai-compatible`, pinned model `ollama-remote/qwen3.8:27b-mlx`,
  `disabled_providers: ["ollama"]`, permissions `ask`/`ask`/`allow`.
- `agents/*.md` — `review`, `security`, `docs`, `test`, `infra`,
  `heaven-backend`, `heaven-frontend`, `dragonwarrior`, `ai`.
- `agent -> agents` symlink (opencode reads one or the other depending on the
  version, same as `install.sh`).
- helper scripts: `refresh-models.py`, `pin-model.sh`, `diag.sh`,
  `fix-service.sh`, `shell-aliases.sh`.

### The config source lives outside the build context

`opencode-global/` is **sibling to `AI/`**, i.e. outside `images/opencode-global`
(the build context). A symlink pointing out of the context is not followed by
BuildKit (a build with `source -> ../..` failed with `transferring context: 55B`
then `not found`), so the files are **copied into the context** in `config/`
instead. `config/` is a mirror you refresh by hand from the source of truth —
nothing in the Makefile or the image pulls automatically, to stay reproducible:

```bash
# refresh the baked config from the source of truth, then rebuild:
cp -R ~/OpenCode/opencode-global/. images/opencode-global/config/
make build NAME=opencode-global
```

The `.dockerignore` keeps the `images/opencode/` conventions (`*.sh`, `*.md`,
`Dockerfile`) but, because they match only top-level paths, the multi-segment
`config/*.md`, `config/*.sh` and `config/*.py` (the agents and helpers) are still
copied — only the macOS/launchd bits are excluded: `config/install.sh`,
`config/net.famillelallier.opencode.plist`, `config/README.md`, plus the
`Dockerfile` itself.

### Server binding

The baked `opencode.json` keeps `server.hostname: 127.0.0.1` (the local value).
Container reachability comes from the `CMD` flag
`opencode serve --hostname 0.0.0.0 --port 4096` — the flag outranks the config
field, so the config file stays unmutated and the container is still reachable.

### The provider URL is unchanged (known risk)

The provider points in cleartext at `http://192.168.2.40:11434` on the LAN. It
is **kept as-is**: it is only reachable from that network, and the URL is not
rewritten at build time. Override it at runtime if you point elsewhere
(e.g. mount a fresh `opencode.json`, or run `refresh-models.py` inside the
container against another Ollama — needs `python3`).

### Build and run

Prerequisite: `opencode:latest` must be present locally (this image uses it in
`FROM`), else build it first. Colima must be up.

```bash
make status                     # Colima up? if not: make up
make build NAME=opencode                       # required first (FROM opencode:latest)
make build NAME=opencode-global
make run   NAME=opencode-global               # opencode serve --hostname 0.0.0.0 --port 4096
make shell NAME=opencode-global              # /bin/sh in the image
```

> `make run NAME=opencode-global` binds host `4096`; free it first if another
> opencode server is already listening. `make push` / `make clean` are destructive
> on a registry / on every container on the machine — not run here.

## Compose stack

`compose.yaml` runs the images as a local dev stack. Settings come from a `.env`
file at the repo root (Compose reads it automatically):

```bash
cp .env.example .env
```

| Variable           | Default        | Purpose                                    |
| ------------------ | -------------- | ------------------------------------------ |
| `TAG`              | `latest`       | Tag for the locally built images           |
| `OPENCODE_VERSION` | `1.18.25`      | opencode release pinned at build time      |
| `OPENCODE_PORT`    | `4096`         | Host port for the opencode server          |
| `OPENCODE_BIND`    | `127.0.0.1`    | Host interface the port is published on    |
| `OPENCODE_SERVER_PASSWORD` | _(empty)_ | Auth for the opencode server          |
| `WORKSPACE`        | `./workspace`  | Host directory mounted at `/work`          |
| `ANTHROPIC_API_KEY`| _(empty)_      | Passed through to the container if set     |

```bash
make compose-build        # build the service images
make compose-up           # start in the background
make compose-ps           # status (incl. health)
make compose-logs         # follow logs (SERVICE=opencode to narrow)
make compose-shell SERVICE=opencode
make compose-down         # stop and remove containers
make compose-clean        # also remove named volumes
```

The opencode server then answers on <http://localhost:4096>, e.g.
`curl http://localhost:4096/global/health`.

### Services

- **opencode** — `images/opencode`, serving on `4096`. Uses the image's own
  healthcheck. State persists in the `opencode-data` and `opencode-config`
  volumes; the workspace is a bind mount so edits are visible on the host.

> The opencode server is unauthenticated unless `OPENCODE_SERVER_PASSWORD` is
> set, so the port is published on `127.0.0.1` only. Set a password before
> changing `OPENCODE_BIND`.

> The container runs as uid `10001`. If writes into `/work` fail on a Linux
> host, `chown 10001 workspace/` (or point `WORKSPACE` at a directory that uid
> can write).

## Adding a new image

1. Create `images/<name>/Dockerfile` (and a `.dockerignore` if useful).
2. Build and verify: `make build NAME=<name>` then `make shell NAME=<name>`.
3. Push: `make push NAME=<name> REGISTRY=ghcr.io/<you>`.

## License

Unlicensed — all rights reserved.
