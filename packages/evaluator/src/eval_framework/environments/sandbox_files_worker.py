"""旧 worker 路径；兼容包内导入、模块执行与独立解释器。"""

if __package__:
    from .file_tools.worker_script import execute, main
    from .file_tools.worker_script import safe_path as _safe_path
    from .file_tools.worker_script import snapshot as _snapshot
else:
    import runpy
    from pathlib import Path

    builder = runpy.run_path(str(Path(__file__).with_name("file_tools") / "payload.py"))
    namespace = {"__name__": "_file_tools_worker", "__package__": None}
    exec(
        compile(builder["build_worker_script"](), "<file-tools-payload>", "exec"),
        namespace,
    )
    execute, main = namespace["execute"], namespace["main"]
    _safe_path, _snapshot = namespace["safe_path"], namespace["snapshot"]


def safe_path(root, value):
    """保留旧 helper 的 root 关键字参数。"""
    return _safe_path(root, value)


def snapshot(root):
    """保留旧 helper 的 root 关键字参数。"""
    return _snapshot(root)


__all__ = ["execute", "main", "safe_path", "snapshot"]

if __name__ == "__main__":
    main()
