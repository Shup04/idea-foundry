.PHONY: check deps ui-env
deps:
	mkdir -p .dev-wheels
	chmod 777 .dev-wheels
	docker run --rm -i --cap-drop=ALL --read-only --tmpfs /tmp -v "$(CURDIR)/.dev-wheels:/wheels" python:3.13-slim python -m pip download --disable-pip-version-check --only-binary=:all: --dest /wheels -r /dev/stdin < requirements.txt
	chmod 755 .dev-wheels

ui-env:
	python3 -m venv .venv
	.venv/bin/python -m pip install --no-index --find-links .dev-wheels -r requirements.txt

check:
	docker build --network=none --pull=false -f Dockerfile.dev -t idea-foundry-check:local .
	docker run --rm --network=none --read-only --tmpfs /tmp --cap-drop=ALL idea-foundry-check:local
