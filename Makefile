.PHONY: check fmt lint test e2e xtest icons run

check: lint test e2e

lint:
	ruff format --check .
	ruff check .
	mypy
	npx biome ci .

fmt:
	ruff format .
	ruff check --fix .
	npx biome check --write .

test:
	pytest
	node --test "tests/js/*.test.js"

# real server (recorded input, loopback only) + headless Chrome (CHROME_PATH, default /usr/bin/google-chrome)
e2e:
	node --test --test-concurrency=1 "tests/e2e/*.test.js"

# XTest typing against a throwaway nested X server (Xephyr, opens a small window briefly)
xtest:
	scripts/with-test-display.sh pytest -m xserver

icons:
	python scripts/make_icons.py

run:
	phonepad serve
