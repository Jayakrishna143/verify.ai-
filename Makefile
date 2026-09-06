.PHONY: install download chunk index index-force ingest serve stop check clean

install:
	uv sync

download:
	uv run python -m ingest.run

chunk:
	uv run python -m ingest.run --chunk

index:
	uv run python -m retrieval.run --build

index-force:
	uv run python -m retrieval.run --build --force

ingest: download index

check:
	uv run python -m retrieval.run

ifeq ($(OS),Windows_NT)

serve:
	pwsh -NoLogo -Command "Start-Process pwsh -ArgumentList '-NoExit','-Command','uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload'; Write-Host 'UI -> http://localhost:8000'"

stop:
	pwsh -NoLogo -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $$_.OwningProcess -Force -ErrorAction SilentlyContinue }; Write-Host 'Stopped'"

clean:
	pwsh -NoLogo -Command "Get-ChildItem -Recurse -Force -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; Write-Host 'Cleaned'"

else

serve:
	tmux new-session -d -s verifyai 'uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload' 2>/dev/null; \
	echo "UI -> http://localhost:8000"

stop:
	tmux kill-session -t verifyai 2>/dev/null; true

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true

endif
