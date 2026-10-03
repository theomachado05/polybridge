.PHONY: setup-research test-research setup-backend test-backend build-engine test-engine test-engine-py setup-web test-web test

setup-research:
	cd research && uv venv .venv && uv pip install --python .venv -e ".[dev]"

test-research:
	cd research && .venv/bin/python -m pytest -q

setup-backend:
	cd backend && uv sync --locked

test-backend:
	cd backend && uv run --locked pytest -q

build-engine:
	cmake -S engine/hedgecore -B engine/hedgecore/build -G Ninja -DCMAKE_BUILD_TYPE=Release
	cmake --build engine/hedgecore/build

test-engine: build-engine
	ctest --test-dir engine/hedgecore/build --output-on-failure

setup-web:
	cd web && pnpm install

test-web:
	cd web && pnpm lint && pnpm build

test-engine-py:
	cd backend && uv sync --locked --group engine && uv run pytest ../engine/hedgecore/tests -q

test: test-research test-backend test-engine test-engine-py test-web
