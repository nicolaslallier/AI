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
├── images/            # Per-image build directories
│   └── <name>/
│       ├── Dockerfile
│       └── .dockerignore
├── Makefile           # Build / push / lifecycle helpers
└── README.md
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

## Adding a new image

1. Create `images/<name>/Dockerfile` (and a `.dockerignore` if useful).
2. Build and verify: `make build NAME=<name>` then `make shell NAME=<name>`.
3. Push: `make push NAME=<name> REGISTRY=ghcr.io/<you>`.

## License

Unlicensed — all rights reserved.
