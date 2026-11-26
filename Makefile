.PHONY: install build-web api dev-web test demo seed clean

install:
	pip install -r requirements.txt
	npm --prefix web install
	npm --prefix web run build

build-web:
	npm --prefix web run build

api:
	uvicorn server.main:app --host 127.0.0.1 --port 8000

dev-web:
	npm --prefix web run dev

test:
	python -m pytest -q

seed:
	python scripts/seed_demo.py

demo: seed
	uvicorn server.main:app --host 127.0.0.1 --port 8000

clean:
	rm -rf web/dist web/node_modules .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
