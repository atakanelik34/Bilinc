"""Build hooks for the public cloud-only artifact boundary.

The source-only scheduler remains importable for the internal runtime, but it
must not be copied into the public wheel. ``MANIFEST.in`` already excludes it
from the sdist; this hook applies the same boundary to setuptools' Python
module discovery for wheels.
"""

from setuptools import setup
from setuptools.command.build_py import build_py


class CloudOnlyBuildPy(build_py):
    """Exclude source-only runtime modules from the public wheel."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            module
            for module in modules
            if not (module[0] == "bilinc" and module[1] == "scheduler")
        ]


setup(cmdclass={"build_py": CloudOnlyBuildPy})
