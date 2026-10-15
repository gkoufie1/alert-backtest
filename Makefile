.PHONY: up down nuke venv test errors latency baseline capture backtest replay

PY ?= python3

up:          ## start app, Prometheus and load generator
	docker compose up -d --build

down:        ## stop everything, keep Prometheus data
	docker compose down

nuke:        ## stop everything and delete Prometheus data
	docker compose down -v

venv:
	$(PY) -m venv .venv && .venv/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

errors:      ## 20% errors for 5 minutes
	$(PY) tools/inject.py --type errors --magnitude 0.2 --duration 300

latency:     ## +800ms latency for 5 minutes
	$(PY) tools/inject.py --type latency --magnitude 800 --duration 300

baseline:    ## 30 minutes of normal traffic, for false-positive scoring
	$(PY) tools/inject.py --type none --duration 1800

capture:     ## save incident windows to Parquet
	$(PY) tools/capture.py

backtest:    ## replay rules/alerts.yaml against every recorded incident
	$(PY) -m engine.backtest

replay:      ## same backtest, replayed from the Parquet library (no live Prometheus needed)
	$(PY) -m engine.backtest --source replay
