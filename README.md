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

## Source Code Modification

This repository, including the package that distributes to pypi,
contains [Xray-core](https://github.com/XTLS/Xray-core) source code that's been
modified to build the binding and specific API. If without explicitly remark, the version of this package corresponds to
the version of the origin source code tag, so the binding will have full features as the original go distribution will
have. And due to its backward compatibility, there's no plan to generate bindings for older release of Xray-core.

To make installation of this package easier, I didn't add the original [Xray-core](https://github.com/XTLS/Xray-core)
source code as a submodule. To track what modifications have been made to the source code, you can compare it with the
same version under Python binding and corresponding go repository.

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
