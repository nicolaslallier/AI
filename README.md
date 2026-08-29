# Colima / Dev Env Images

Repository holding Docker images used in the local development environment (via [Colima](https://github.com/abiosoft/colima)).

## Structure

```
.
├── images/        # Per-image build directories (each has a Dockerfile)
│   └── <name>/Dockerfile
├── compose.yaml   # Local dev stack wiring the images together
├── .env.example   # Template for compose settings (copy to .env)
├── workspace/     # Host directory mounted into the containers
└── Makefile       # Helpers to build/push images and drive compose
```

## Usage

```bash
# Build an image
make build NAME=<name>

# Push to your registry
make push NAME=<name> REGISTRY=ghcr.io/<you>
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
