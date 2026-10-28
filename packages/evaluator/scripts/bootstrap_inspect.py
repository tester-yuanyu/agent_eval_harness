"""Install local Suite packages and the declared public Inspect dependency."""

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--agent-path", type=Path, help="Optional local minimal-agent project"
    )
    args = parser.parse_args()
    extension = Path(__file__).resolve().parents[1]
    packages = extension.parent
    projects = [packages / "contracts", packages / "agent-trace-sdk"]
    if args.agent_path:
        projects.append(args.agent_path.resolve())
    extras = "dev"
    command = [sys.executable, "-m", "pip", "install"]
    for project in projects:
        command.extend(["-e", str(project)])
    command.extend(["-e", f"{extension}[{extras}]"])
    subprocess.run(command, check=True)
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    # A fresh process is required to verify new editable import mappings.
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
from importlib.metadata import version
from pathlib import Path
import inspect_ai, eval_framework, agent_trace_sdk
import sys
assert version('inspect_ai') == '0.3.280'
extension = Path(sys.argv[2]).resolve()
assert Path(eval_framework.__file__).resolve().is_relative_to(extension)
sdk_root = Path(sys.argv[1]).resolve()
assert Path(agent_trace_sdk.__file__).resolve().is_relative_to(sdk_root)
print('Pinned Inspect, Evaluator extension and evidence SDK imports verified.')
""",
            str(packages / "agent-trace-sdk"),
            str(extension),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
