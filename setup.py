import os
import pathlib
import platform
import shlex
import shutil
import subprocess
import sys

from setuptools import Extension, find_packages, setup
from setuptools.command.build_ext import build_ext


ROOT_DIR = pathlib.Path(__file__).parent.resolve()
PACKAGE_NAME = 'Xray-core'
BINDING_NAME = 'xray'


def getXrayCoreVersion():
    return '1.8.26.9'


class CMakeExtension(Extension):
    '''A setuptools extension whose sources are built by CMake.'''

    def __init__(self, name):
        super().__init__(name, sources=[])


class BuildXrayCore(build_ext):
    '''Build the Go archive and CMake extension for the active interpreter.'''

    def build_extension(self, ext):
        if self.dry_run:
            return

        extension_path = pathlib.Path(self.get_ext_fullpath(ext.name)).resolve()
        build_dir = pathlib.Path(self.build_temp).resolve() / ext.name
        go_output_dir = build_dir / 'go'
        cmake_build_dir = build_dir / 'cmake'
        native_output_dir = build_dir / 'native'

        for directory in (go_output_dir, cmake_build_dir, native_output_dir):
            directory.mkdir(parents=True, exist_ok=True)

        archive_name = 'xray.lib' if platform.system() == 'Windows' else 'xray.a'
        archive_path = go_output_dir / archive_name

        env = os.environ.copy()
        env['CGO_ENABLED'] = '1'
        # The Go objects do not depend on the Python ABI, so keep one cache
        # across all cibuildwheel interpreter builds on this platform.
        env['GOCACHE'] = str(ROOT_DIR / 'build' / 'go-cache')

        macos_architecture = None

        if platform.system() == 'Darwin':
            macos_architecture = self.macos_architecture(env)

            if macos_architecture:
                go_architectures = {
                    'arm64': 'arm64',
                    'x86_64': 'amd64',
                }

                try:
                    env['GOARCH'] = go_architectures[macos_architecture]
                except KeyError as error:
                    raise RuntimeError(
                        f'Unsupported macOS architecture: {macos_architecture}'
                    ) from error

                env['GOOS'] = 'darwin'

        self.run_command(
            [
                'go',
                'build',
                '-o',
                str(archive_path),
                '-buildmode=c-archive',
                '-trimpath',
                '-ldflags',
                '-s -w -buildid=',
                './main',
            ],
            cwd=ROOT_DIR / 'xray-go',
            env=env,
        )

        cmake_args = [
            'cmake',
            '-S',
            str(ROOT_DIR),
            '-B',
            str(cmake_build_dir),
            '-DCMAKE_BUILD_TYPE=Release',
            f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={native_output_dir.as_posix()}',
            f'-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={native_output_dir.as_posix()}',
            f'-DCMAKE_LIBRARY_OUTPUT_DIRECTORY_RELEASE={native_output_dir.as_posix()}',
            f'-DCMAKE_RUNTIME_OUTPUT_DIRECTORY_RELEASE={native_output_dir.as_posix()}',
            f'-DPython_EXECUTABLE={pathlib.Path(sys.executable).as_posix()}',
            self.pybind11_cmake_argument(),
            f'-DXRAY_CORE_ARCHIVE={archive_path.as_posix()}',
            f'-DXRAY_CORE_INCLUDE_DIR={go_output_dir.as_posix()}',
        ]

        if macos_architecture:
            cmake_args.append(
                f'-DCMAKE_OSX_ARCHITECTURES={macos_architecture}'
            )

        if platform.system() == 'Windows':
            cmake_args.extend(
                [
                    '-G',
                    'MinGW Makefiles',
                    '-DCMAKE_C_COMPILER=gcc',
                    '-DCMAKE_CXX_COMPILER=g++',
                ]
            )

        self.run_command(cmake_args, cwd=ROOT_DIR, env=env)
        self.run_command(
            [
                'cmake',
                '--build',
                str(cmake_build_dir),
                '--config',
                'Release',
                '--target',
                BINDING_NAME,
                '--parallel',
            ],
            cwd=ROOT_DIR,
            env=env,
        )

        candidates = []
        for pattern in ('xray*.pyd', 'xray*.so', 'xray*.dylib'):
            candidates.extend(native_output_dir.rglob(pattern))

        if len(candidates) != 1:
            found = ', '.join(str(path) for path in candidates) or 'none'
            raise RuntimeError(f'Expected one native xray extension, found: {found}')

        extension_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidates[0], extension_path)

    @staticmethod
    def run_command(command, cwd, env):
        subprocess.run(command, cwd=str(cwd), env=env, check=True)

    @staticmethod
    def pybind11_cmake_argument():
        import pybind11

        cmake_dir = pathlib.Path(pybind11.get_cmake_dir())
        return f'-Dpybind11_DIR={cmake_dir.as_posix()}'

    @staticmethod
    def macos_architecture(env):
        flags = shlex.split(env.get('ARCHFLAGS', ''))

        architectures = []

        for index, flag in enumerate(flags):
            if flag != '-arch':
                continue
            if index + 1 == len(flags):
                raise RuntimeError('ARCHFLAGS ends with -arch but no architecture')

            architecture = flags[index + 1]

            if architecture not in architectures:
                architectures.append(architecture)

        if len(architectures) > 1:
            raise RuntimeError(
                'Universal2 builds are not supported by the Go c-archive build; '
                'build separate arm64 and x86_64 wheels instead'
            )

        return architectures[0] if architectures else None


with (ROOT_DIR / 'README.md').open('r', encoding='utf-8') as file:
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
    python_requires='>=3.8',
    cmdclass={'build_ext': BuildXrayCore},
    ext_modules=[CMakeExtension('xray.xray')],
    packages=find_packages(),
    include_package_data=True,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)',
        'Intended Audience :: Developers',
        'Programming Language :: C++',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: 3.13',
        'Programming Language :: Python :: 3.14',
        'Operating System :: Microsoft :: Windows',
        'Operating System :: POSIX :: Linux',
        'Operating System :: MacOS :: MacOS X',
        'Topic :: Internet',
        'Topic :: Internet :: Proxy Servers',
    ],
    zip_safe=False,
)
