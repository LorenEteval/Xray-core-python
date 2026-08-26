# Xray-core-python

[![Deploy PyPI](https://github.com/LorenEteval/Xray-core-python/actions/workflows/deploy-pypi.yml/badge.svg?branch=main)](https://github.com/LorenEteval/Xray-core-python/actions/workflows/deploy-pypi.yml)

Python bindings for [Xray-core](https://github.com/XTLS/Xray-core).

## Install

Prebuilt binary wheels include the native Go and C++ binding, so a supported installation does not require Go, CMake,
or a C++ compiler.

```
pip install Xray-core
```

Binary wheels are published for Linux x86-64 and ARM64, Windows x86-64 and ARM64, and macOS Intel and Apple Silicon.

### Build from Source

A source distribution is also published as a fallback. If pip cannot find a compatible wheel, it may build the native
binding from source. A source build requires:

* [Go 1.26 or newer](https://go.dev/doc/install) in `PATH`.
* A working C and C++ compiler toolchain.
* MinGW-w64 on Windows x86-64, or LLVM-MinGW on Windows ARM64, with `gcc` and `g++` available in `PATH`.

The isolated Python build environment installs CMake, pybind11, setuptools, and wheel automatically. To build directly
from a repository checkout:

```
pip install .
```

## API

```pycon
>>> import xray
>>> help(xray) 
Help on package xray:                                                                                                                                                                                       

NAME
    xray

PACKAGE CONTENTS
    xray

FUNCTIONS
    queryStats(...) method of builtins.PyCapsule instance
        queryStats(apiServer: str, timeout: int, myPattern: str, reset: bool) -> str

        Query statistics from Xray

    startFromJSON(...) method of builtins.PyCapsule instance
        startFromJSON(json: str) -> None

        Start Xray client with JSON string
```

## Vendored Xray-core Source

The source distribution vendors an exact [Xray-core](https://github.com/XTLS/Xray-core) release so users can build the
native binding without resolving a Git submodule. Binding-owned Go files are maintained separately from upstream-owned
files, and a checked-in SHA-256 manifest makes unexpected changes fail validation.

`UPSTREAM_VERSION`, `UPSTREAM_COMMIT`, and the files under `upstream/` record the exact source provenance.

## Binary Wheel Platforms

The distributions are built and tested in [GitHub Actions](https://github.com/LorenEteval/Xray-core-python/actions).

| Platform | Architecture | CPython |
|----------|--------------|---------|
| Linux | x86-64 | 3.8-3.14, 3.13t, 3.14t |
| Linux | ARM64 | 3.8-3.14, 3.13t, 3.14t |
| Windows | x86-64 | 3.8-3.14, 3.13t, 3.14t |
| Windows | ARM64 | 3.9-3.14, 3.13t, 3.14t |
| macOS | Intel | 3.8-3.14, 3.13t, 3.14t |
| macOS | Apple Silicon | 3.8-3.14, 3.13t, 3.14t |

## License

The license for this project follows its original go repository [Xray-core](https://github.com/XTLS/Xray-core)
and is under [MPL 2.0](https://github.com/LorenEteval/Xray-core-python/blob/main/LICENSE).
