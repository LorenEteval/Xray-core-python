from setuptools import setup, find_packages
from setuptools.command.install import install

import re
import pathlib
import platform
import subprocess

PLATFORM = platform.system()
ROOT_DIR = pathlib.Path().resolve()
PACKAGE_NAME = 'Xray-core'
BINDING_NAME = 'xray'
CMAKE_BUILD_CACHE = 'CMakeBuildCache'


def getXrayCoreVersion():
    return '1.8.24.2'


def runCommand(command):
    subprocess.run(command, check=True)


def buildXrayCore():
    output = f'{BINDING_NAME}.lib' if PLATFORM == 'Windows' else f'{BINDING_NAME}.a'

    runCommand(
        [
            'go',
            'build',
            '-C',
            'xray-go',
            '-o',
            f'{ROOT_DIR / "gobuild" / output}',
            '-buildmode=c-archive',
            '-trimpath',
            '-ldflags',
            '-s -w -buildid=',
            './main',
        ]
    )


def buildBindings():
    configureCache = [
        'cmake',
        '-S',
        '.',
        '-B',
        CMAKE_BUILD_CACHE,
        '-DCMAKE_BUILD_TYPE=Release',
    ]

    if PLATFORM == 'Windows':
        configureCache += ['-G', 'MinGW Makefiles']

    runCommand(configureCache)

    runCommand(
        [
            'cmake',
            '--build',
            CMAKE_BUILD_CACHE,
            '--target',
            BINDING_NAME,
        ]
    )


class InstallXrayCore(install):
    def run(self):
        buildXrayCore()
        buildBindings()

        install.run(self)


with open('README.md', 'r', encoding='utf-8') as file:
    long_description = file.read()


setup(
    name=PACKAGE_NAME,
    version=getXrayCoreVersion(),
    license='MPL 2.0',
    description='Python bindings for Xray-core, the best v2ray-core with XTLS support.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Loren Eteval',
    author_email='loren.eteval@proton.me',
    url='https://github.com/LorenEteval/Xray-core-python',
    cmdclass={'install': InstallXrayCore},
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Intended Audience :: Developers',
        'Programming Language :: C++',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Operating System :: OS Independent',
        'Topic :: Internet',
        'Topic :: Internet :: Proxy Servers',
    ],
    zip_safe=False,
)
