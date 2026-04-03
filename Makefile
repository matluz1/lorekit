.PHONY: tui serve status stop test lint

tui:
	cd examples/tui && npx tsx src/index.tsx

serve:
	uv run lorekit serve

status:
	uv run lorekit status

stop:
	@pkill -f "lorekit.server" 2>/dev/null || true
	@pkill -f "lorekit.http_server" 2>/dev/null || true
	@echo "Server stopped."

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .
