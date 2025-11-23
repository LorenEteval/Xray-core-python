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

This repository, including the package that distributes to pypi,
contains [Xray-core](https://github.com/XTLS/Xray-core) source code that's been
modified to build the binding and specific API. If without explicitly remark, the version of this package corresponds to
the version of the origin source code tag, so the binding will have full features as the original go distribution will
have. And due to its backward compatibility, there's no plan to generate bindings for older release of Xray-core.

To make installation of this package easier, I didn't add the original [Xray-core](https://github.com/XTLS/Xray-core)
source code as a submodule. To track what modifications have been made to the source code, you can compare it with the
same version under Python binding and corresponding go repository.

## Tested Platform

Xray-core-python works on all major platform with all Python version(Python 3).

Below are tested build in [github actions](https://github.com/LorenEteval/Xray-core-python/actions).

| Platform     | Python 3.8-Python 3.14 |
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
