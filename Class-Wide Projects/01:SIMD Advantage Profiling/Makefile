.PHONY: build test evidence quick full clean
build:
	python3 scripts/build.py
test: build
	python3 tests/test_correctness.py
	python3 tests/test_analysis.py
evidence: build
	python3 scripts/evidence.py
quick:
	bash scripts/run_all.sh quick
full:
	bash scripts/run_all.sh full
clean:
	rm -rf build build-sanitize
