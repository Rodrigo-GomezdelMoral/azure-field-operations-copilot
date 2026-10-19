PYTHON ?= python
RESOURCE_GROUP ?= rg-fopcopilot-prod-swc
LZ_OUTPUTS ?= ../lz-outputs.txt

.PHONY: install lint type test budget check seed index analyzer eval smoke run mcp a2a web lz-env validate-infra preview deploy destroy

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

lint:
	ruff check . && ruff format --check .

type:
	mypy

test:
	pytest -q

budget:
	pytest -q tests/test_budget.py

check: lint type test

seed:
	$(PYTHON) -m ops.seed

index:
	$(PYTHON) -m ops.index

analyzer:
	$(PYTHON) -m ops.analyzer

eval:
	$(PYTHON) -m eval.run --suite full

smoke:
	$(PYTHON) -m eval.run --suite smoke

run:
	uvicorn app.main:app --reload --port 8000

mcp:
	$(PYTHON) -m mcp_inventory.server

a2a:
	uvicorn a2a_server.main:app --port 8010

web:
	cd web && npm ci && npm run build && npm start

lz-env:
	@export MSYS_NO_PATHCONV=1; grep -E '^[a-z][A-Za-z]+=' $(LZ_OUTPUTS) | while IFS='=' read -r key value; do \
	  name=$$(echo "$$key" | sed -E 's/([a-z0-9])([A-Z])/\1_\2/g' | tr '[:lower:]' '[:upper:]'); \
	  azd env set "$$name" "$$(echo "$$value" | tr -d '"')"; \
	done

validate-infra:
	az bicep build --file infra/main.bicep --stdout --only-show-errors > /dev/null && az bicep lint --file infra/main.bicep --only-show-errors

preview:
	azd provision --preview --no-prompt

deploy:
	azd up --no-prompt

destroy:
	azd down --force --purge
