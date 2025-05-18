# Xray-core-python

[![Deploy PyPI](https://github.com/LorenEteval/Xray-core-python/actions/workflows/deploy-pypi.yml/badge.svg?branch=main)](https://github.com/LorenEteval/Xray-core-python/actions/workflows/deploy-pypi.yml)

Python bindings for [Xray-core](https://github.com/XTLS/Xray-core).

## Install

### Core Building Tools

You have to install the following tools to be able to install this package successfully.

* [go](https://go.dev/doc/install) in your PATH. go 1.20.0 and above is recommended. To check go is ready,
  type `go version`. Also, if google service is blocked in your region(such as Mainland China), you have to configure
  your GOPROXY to be able to pull go packages. For Chinese users, refer to [goproxy.cn](https://goproxy.cn/) for more
  information.
* [cmake](https://cmake.org/download/) in your PATH. To check cmake is ready, type `cmake --version`.
* A working GNU C++ compiler(i.e. GNU C++ toolchains). To check GNU C++ compiler is ready, type `g++ --version`. These
  tools should have been installed in Linux or macOS by default. If you don't have GNU C++ toolchains(especially for
  Windows users) anyway:

    * For Linux users: type `sudo apt update && sudo apt install g++` and that should work out fine.
    * For Windows users: install [MinGW-w64](https://sourceforge.net/projects/mingw-w64/files/mingw-w64/)
      or [Cygwin](https://www.cygwin.com/) and make sure you have add them to PATH.

### Install Package

```
pip install Xray-core
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

This repository—including the package distributed on PyPI—contains source code from Xray-core, which has been modified
to build Python bindings and expose a specific API. Unless otherwise noted, the version of this package aligns with the
corresponding tag of the original source code, ensuring that the binding provides the same full feature set as the
official Go distribution. Due to Xray-core's backward compatibility, there are no plans to generate bindings for
older releases.

To simplify installation, the original Xray-core source code is not included as a submodule. To track the modifications
made, you can compare the Python binding's source code against the corresponding version in the upstream Go repository.

## Tested Platform

Xray-core-python works on all major platform with all Python version(Python 3).

Below are tested build in [github actions](https://github.com/LorenEteval/Xray-core-python/actions).

| Platform     | Python 3.8-Python 3.13 |
|--------------|:----------------------:|
| ubuntu 22.04 |   :heavy_check_mark:   |
| ubuntu 24.04 |   :heavy_check_mark:   |
| windows-2019 |   :heavy_check_mark:   |
| windows-2022 |   :heavy_check_mark:   |
| windows-2025 |   :heavy_check_mark:   |
| macos-13     |   :heavy_check_mark:   |
| macos-14     |   :heavy_check_mark:   |
| macos-15     |   :heavy_check_mark:   |

## License

The license for this project follows its original go repository [Xray-core](https://github.com/XTLS/Xray-core)
and is under [MPL 2.0](https://github.com/LorenEteval/Xray-core-python/blob/main/LICENSE).
