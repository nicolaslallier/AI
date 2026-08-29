# Colima / Dev Env Images

Repository holding Docker images used in the local development environment (via [Colima](https://github.com/abiosoft/colima)).

## Structure

```
.
├── images/        # Per-image build directories (each has a Dockerfile)
│   └── <name>/Dockerfile
└── Makefile       # Helpers to build/push images
```

## Usage

```bash
# Build an image
make build NAME=<name>

# Push to your registry
make push NAME=<name> REGISTRY=ghcr.io/<you>
```
