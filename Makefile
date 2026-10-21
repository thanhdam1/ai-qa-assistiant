.PHONY: help install up down test lint eval demo

help:
	@echo "Available commands:"
	@echo "  make install  - Install Python dependencies"
	@echo "  make up       - Start Docker Compose services (Qdrant & Backend)"
	@echo "  make down     - Stop Docker Compose services"
	@echo "  make test     - Run pytest test suite"
	@echo "  make lint     - Check code syntax across backend"
	@echo "  make eval     - Run Ragas & Codebase Benchmark evaluation"
	@echo "  make demo     - Run enterprise 5-pillar demo walkthrough"

install:
	pip install -r backend/requirements.txt

up:
	docker compose up -d --build

down:
	docker compose down

test:
	pytest backend/tests/ -v

lint:
	python -m py_compile backend/app/main.py

eval:
	python evaluation/run_ragas_eval.py

demo:
	python scripts/demo_walkthrough.py
