import os
from pathlib import Path
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.egg_info import egg_info as _egg_info
from setuptools.command.install import install as _install


ROOT = Path(__file__).resolve().parent


def ensure_node_dependencies():
    package_json = ROOT / "package.json"
    if not package_json.exists():
        raise FileNotFoundError("package.json was not found; cannot install Node.js dependencies.")

    npm_command = "npm.cmd" if os.name == "nt" else "npm"
    print(f"Running {npm_command} install for Render compatibility...")
    subprocess.run([npm_command, "install"], check=True, cwd=ROOT)


class build_py(_build_py):
    def run(self):
        ensure_node_dependencies()
        super().run()


class egg_info(_egg_info):
    def run(self):
        ensure_node_dependencies()
        super().run()


class install(_install):
    def run(self):
        ensure_node_dependencies()
        super().run()


setup(
    name="shamba-assistant-build-helper",
    version="0.0.0",
    description="Build helper so Render can install Node.js dependencies from a legacy pip build command.",
    packages=[],
    py_modules=["render_build_helper"],
    cmdclass={
        "build_py": build_py,
        "egg_info": egg_info,
        "install": install,
    },
)
