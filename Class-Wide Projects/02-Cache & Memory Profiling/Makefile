CXX ?= g++
CXXFLAGS ?= -O3 -std=c++17 -Wall -Wextra -Wpedantic -pthread -fno-tree-vectorize
LDLIBS = -pthread

all: build/membench

build/membench: src/membench.cpp
	mkdir -p build
	$(CXX) $(CXXFLAGS) $< -o $@ $(LDLIBS)

test: all
	python3 tests/test_suite.py

clean:
	rm -rf build

.PHONY: all test clean
