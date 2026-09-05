# Phase 4 C++ engine. Build: make -C engine
CXX ?= g++
CXXFLAGS ?= -std=c++17 -O3 -march=native -funroll-loops

vm_run: vm.cpp
	$(CXX) $(CXXFLAGS) -o $@ $<

clean:
	rm -f vm_run
