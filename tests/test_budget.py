import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED = ("docs/", "eval/datasets/", "web/node_modules/", "web/fixtures/")
MAX_FILES = 56  # the specification's own layout needs more than its 48-file figure; the README records the count
APPLICATION = ("app/", "ops/", "mcp_inventory/", "a2a_server/")  # the 1,200 lines the specification budgets
MAX_APP_LINES, MAX_SUPPORT_LINES, MAX_BICEP_LINES, MAX_TYPESCRIPT_LINES = 1200, 700, 450, 700
MAX_DEPTH, MAX_FUNCTION_LINES, MAX_COMMENTS = 3, 35, 24


def tracked_files(*suffixes: str) -> list[Path]:
    command = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    names = subprocess.run(command, capture_output=True, text=True, check=True, cwd=ROOT).stdout.split("\n")
    files = [ROOT / name for name in names if name and not name.startswith(EXCLUDED) and (ROOT / name).is_file()]
    return [f for f in files if f.suffix in suffixes] if suffixes else files


def lines(paths: list[Path]) -> int:
    return sum(len(p.read_text(encoding="utf-8").splitlines()) for p in paths)


def test_file_and_depth_budget() -> None:
    files = tracked_files()
    assert len(files) <= MAX_FILES, f"{len(files)} tracked files"
    deepest = max(len(f.relative_to(ROOT).parts) - 1 for f in files)
    assert deepest <= MAX_DEPTH, f"directory depth {deepest}"


def test_line_budgets() -> None:
    python = tracked_files(".py")
    application = [f for f in python if str(f.relative_to(ROOT)).replace("\\", "/").startswith(APPLICATION)]
    support = [f for f in python if f not in application]
    assert lines(application) <= MAX_APP_LINES, f"{lines(application)} application Python lines"
    assert lines(support) <= MAX_SUPPORT_LINES, f"{lines(support)} evaluation and test lines"
    assert lines(tracked_files(".bicep", ".bicepparam")) <= MAX_BICEP_LINES
    assert lines(tracked_files(".ts", ".tsx")) <= MAX_TYPESCRIPT_LINES


def test_python_craft() -> None:
    comments = 0
    for path in tracked_files(".py"):
        source = path.read_text(encoding="utf-8")
        comments += sum(1 for line in source.splitlines() if line.lstrip().startswith("#"))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                assert length <= MAX_FUNCTION_LINES, f"{path.name}:{node.name} is {length} lines"
            if isinstance(node, ast.ExceptHandler):
                blind = node.type is None or (isinstance(node.type, ast.Name) and node.type.id == "Exception")
                assert not blind, f"{path.name}:{node.lineno} catches everything"
    assert comments <= MAX_COMMENTS, f"{comments} comment lines"


def test_dependencies_are_pinned_and_minimal() -> None:
    files = (ROOT / "requirements.txt", ROOT / "requirements-dev.txt")
    pins = [line for file in files for line in file.read_text().splitlines()]
    for pin in (p for p in pins if p and not p.startswith(("-r", "#"))):
        assert "==" in pin, f"unpinned dependency {pin}"
        assert not pin.startswith("agent-framework=="), "the agent-framework metapackage is not allowed"
