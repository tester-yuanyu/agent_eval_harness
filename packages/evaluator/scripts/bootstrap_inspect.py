"""Install the local Inspect tree, evidence SDK and business extension."""

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
    inspect_repo = extension.parents[1]
    projects = [inspect_repo, extension / "packages/agent_trace_sdk"]
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
from pathlib import Path
import inspect_ai, eval_framework, agent_trace_sdk
import sys
assert Path(inspect_ai.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve())
extension = Path(sys.argv[2]).resolve()
assert Path(eval_framework.__file__).resolve().is_relative_to(extension)
assert Path(agent_trace_sdk.__file__).resolve().is_relative_to(extension)
print('Local Inspect, Evaluator extension and evidence SDK imports verified.')
""",
            str(inspect_repo / "src"),
            str(extension),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
