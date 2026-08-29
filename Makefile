NAME ?=
REGISTRY ?= ghcr.io
TAG ?= latest

.PHONY: build push list

list:
	@ls -1 images

build:
	@docker build -t $(NAME):$(TAG) images/$(NAME)

push:
	@docker tag $(NAME):$(TAG) $(REGISTRY)/$(NAME):$(TAG)
	@docker push $(REGISTRY)/$(NAME):$(TAG)
