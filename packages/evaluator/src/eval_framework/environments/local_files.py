"""旧文件工具入口；兼容包内及扁平 worker 导入。"""

if __package__:
    from ._fs_utils import safe_path, snapshot_files
else:
    from _fs_utils import safe_path, snapshot_files

__all__ = ["safe_path", "snapshot_files"]
