NAME ?=
REGISTRY ?= ghcr.io
TAG ?= latest

.DEFAULT_GOAL := help
.PHONY: help up down status restart list build build-all push push-all run shell logs prune clean

help:
	@echo "Colima / Dev Env Images — available commands"
	@echo ""
	@echo "  Environment (Colima)"
	@echo "    up            Start the Colima VM (docker daemon)"
	@echo "    down          Stop the Colima VM"
	@echo "    status        Show Colima status"
	@echo "    restart       Restart the Colima VM"
	@echo ""
	@echo "  Images"
	@echo "    list          List available image directories"
	@echo "    build         Build an image       (make build NAME=<name>)"
	@echo "    build-all     Build every image in images/"
	@echo "    push          Push an image        (make push NAME=<name>)"
	@echo "    push-all      Push every image in images/"
	@echo "    run           Run an image         (make run NAME=<name>)"
	@echo "    shell         Open a shell in a built image (make shell NAME=<name>)"
	@echo ""
	@echo "  Cleanup"
	@echo "    prune         Remove dangling images and unused resources"
	@echo "    clean         Remove containers and dangling images"
	@echo ""
	@echo "Options: NAME, REGISTRY (default $(REGISTRY)), TAG (default $(TAG))"

up:
	@colima start

down:
	@colima stop

status:
	@colima status

restart: down up

list:
	@ls -1 images | grep -v '^\.$$\|^\.\.\$$\|^\.gitkeep$$'

build:
	@if [ -z "$(NAME)" ]; then echo "Usage: make build NAME=<name>"; exit 1; fi
	@docker build -t $(NAME):$(TAG) images/$(NAME)

build-all:
	@for dir in images/*/; do \
		name=$$(basename $$dir); \
		[ -f "$$dir/Dockerfile" ] || continue; \
		echo "Building $$name ..."; \
		docker build -t $$name:$(TAG) $$dir || exit 1; \
	done

push:
	@if [ -z "$(NAME)" ]; then echo "Usage: make push NAME=<name>"; exit 1; fi
	@docker tag $(NAME):$(TAG) $(REGISTRY)/$(NAME):$(TAG)
	@docker push $(REGISTRY)/$(NAME):$(TAG)

push-all:
	@for dir in images/*/; do \
		name=$$(basename $$dir); \
		[ -f "$$dir/Dockerfile" ] || continue; \
		echo "Pushing $$name ..."; \
		docker tag $$name:$(TAG) $(REGISTRY)/$$name:$(TAG) || exit 1; \
		docker push $(REGISTRY)/$$name:$(TAG) || exit 1; \
	done

run:
	@if [ -z "$(NAME)" ]; then echo "Usage: make run NAME=<name>"; exit 1; fi
	@docker run --rm -it $(NAME):$(TAG)

shell:
	@if [ -z "$(NAME)" ]; then echo "Usage: make shell NAME=<name>"; exit 1; fi
	@docker run --rm -it $(NAME):$(TAG) /bin/sh

prune:
	@docker image prune -f
	@docker system prune -f

clean:
	@docker rm -f $$(docker ps -aq) 2>/dev/null || true
	@docker image prune -f
