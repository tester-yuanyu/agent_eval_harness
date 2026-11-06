"""只装配随包发布的可信源码；任务输入始终通过 JSON 传入。"""

from pathlib import Path


def build_worker_script() -> str:
    directory = Path(__file__).resolve().parent
    helpers = (directory.parent / "_fs_utils.py").read_text(encoding="utf-8")
    worker = (directory / "worker_script.py").read_text(encoding="utf-8")
    return (
        "import sys, types\n"
        "helpers = types.ModuleType('_environment_fs_utils')\n"
        "sys.modules[helpers.__name__] = helpers\n"
        f"exec(compile({helpers!r}, '_fs_utils.py', 'exec'), helpers.__dict__)\n"
        f"exec(compile({worker!r}, 'worker_script.py', 'exec'), "
        "globals())\n"
    )
