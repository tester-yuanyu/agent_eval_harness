"""Include immutable authoring resources in built distributions."""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent
        destination = Path(self.build_lib) / "dataset_builder/resources"
        for name in ("schemas", "suites", "policies", "protocol_profiles"):
            self.copy_tree(str(source / name), str(destination / name))


setup(cmdclass={"build_py": BuildPy})
