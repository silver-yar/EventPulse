SAM := /Users/silveryar/bin/aws-sam-cli/sam
PY := .venv/bin/python

.PHONY: test lint build validate smoke

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m sqlfluff lint .

build:
	$(SAM) build

validate:
	$(SAM) validate

smoke: build
	@mkdir -p /tmp/docker-auth-empty && [ -f /tmp/docker-auth-empty/config.json ] || echo '{}' > /tmp/docker-auth-empty/config.json
	# DOCKER_CONFIG override: local credsStore (osxkeychain) breaks docker-py auth resolution in non-interactive shells
	DOCKER_CONFIG=/tmp/docker-auth-empty $(SAM) local invoke IngestFunction