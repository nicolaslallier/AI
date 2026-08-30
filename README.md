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
