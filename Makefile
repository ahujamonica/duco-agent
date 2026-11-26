.PHONY: demo fixtures test clean fixtures-refresh

demo: fixtures
	python run_demo.py

fixtures:
	python fixtures/generate_fixtures.py

test:
	python -m pytest -q

clean:
	rm -rf outputs .pytest_cache
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
