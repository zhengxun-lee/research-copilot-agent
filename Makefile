# Override the interpreter with: make test PYTHON=/path/to/python
PYTHON ?= python3
PIP    ?= $(PYTHON) -m pip

.PHONY: venv install init run cli test test-web check-web build-web benchmark lint format clean

venv:
	@test -d .venv || $(PYTHON) -m venv .venv
	.venv/bin/python -m pip install -U pip

install:
	$(PIP) install -e ".[dev]"

init:
	$(PYTHON) -m ingest --pdf-dir data/pdfs --output data/knowledge_base.json

run:
	$(PYTHON) web_app.py

cli:
	$(PYTHON) main.py

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m flake8 agent/ llm/ tools/ retrievers/ routing/ ingest/ semantic_router/ tests/ web_app.py web_runtime.py model_settings.py main.py config.py api_config.py config_loader.py --max-line-length=120 --extend-ignore=E203,W503

format:
	$(PYTHON) -m isort agent/ llm/ tools/ retrievers/ routing/ ingest/ semantic_router/ web_app.py web_runtime.py model_settings.py main.py config.py api_config.py config_loader.py --profile=black --line-length=120
	$(PYTHON) -m black agent/ llm/ tools/ retrievers/ routing/ ingest/ semantic_router/ web_app.py web_runtime.py model_settings.py main.py config.py api_config.py config_loader.py --line-length=120

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# Frontend development tasks; Node is not needed to serve checked-in assets.
test-web:
	npm test

check-web:
	npm run check

build-web:
	npm run build:console

benchmark:
	@mkdir -p artifacts
	$(PYTHON) scripts/benchmark_context.py > artifacts/context-benchmark.json
