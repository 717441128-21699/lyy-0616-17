"""暂存区（index）管理模块"""

import os
from typing import Dict, List, Optional

from .objects import (
    GIT_DIR,
    TreeEntry,
    create_blob,
    hash_object,
    parse_tree,
    read_object,
    serialize_tree,
)


INDEX_PATH = os.path.join(GIT_DIR, "index")


def read_index() -> Dict[str, Dict]:
    """
    读取暂存区。
    
    index 格式（简化版，每行一个条目）:
        <mode> <sha1> <path>
    
    Returns:
        字典，key 为文件路径，value 为 {"mode": str, "sha1": str}
    """
    index = {}
    if not os.path.exists(INDEX_PATH):
        return index
    
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            mode, sha1, path = line.split(" ", 2)
            index[path] = {"mode": mode, "sha1": sha1}
    
    return index


def write_index(index: Dict[str, Dict]) -> None:
    """
    写入暂存区。
    
    Args:
        index: 暂存区字典
    """
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    
    lines = []
    for path in sorted(index.keys()):
        entry = index[path]
        lines.append(f"{entry['mode']} {entry['sha1']} {path}")
    
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n" if lines else "")


def add_file(file_path: str) -> None:
    """
    将文件添加到暂存区。
    
    步骤：
    1. 读取文件内容，创建 blob 对象
    2. 更新暂存区中该文件的条目
    
    Args:
        file_path: 文件路径（相对路径）
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    norm_path = os.path.normpath(file_path).replace("\\", "/")
    
    blob_sha1 = create_blob(file_path)
    
    index = read_index()
    index[norm_path] = {
        "mode": "100644",
        "sha1": blob_sha1
    }
    write_index(index)


def add_files(file_paths: List[str]) -> None:
    """批量添加文件到暂存区"""
    for file_path in file_paths:
        add_file(file_path)


def remove_from_index(path: str) -> None:
    """从暂存区移除文件"""
    index = read_index()
    norm_path = os.path.normpath(path).replace("\\", "/")
    if norm_path in index:
        del index[norm_path]
        write_index(index)


def index_to_tree() -> str:
    """
    根据暂存区内容构建 tree 对象并返回其 SHA-1。
    
    这是 commit 操作的关键步骤：将暂存区中的扁平文件列表
    转换为递归的 tree 对象结构。
    
    Returns:
        根 tree 的 SHA-1
    """
    index = read_index()
    
    tree_map: Dict[str, List[TreeEntry]] = {}
    tree_map[""] = []
    
    for path, entry in sorted(index.items()):
        parts = path.split("/")
        dir_path = "/".join(parts[:-1])
        file_name = parts[-1]
        
        if dir_path not in tree_map:
            tree_map[dir_path] = []
        
        tree_map[dir_path].append(TreeEntry(
            entry["mode"],
            file_name,
            entry["sha1"]
        ))
    
    all_dirs = sorted(tree_map.keys(), key=lambda x: x.count("/"), reverse=True)
    
    for dir_path in all_dirs:
        if dir_path == "":
            continue
        
        entries = tree_map[dir_path]
        tree_data = serialize_tree(entries)
        tree_sha1 = hash_object(tree_data, "tree")
        
        parts = dir_path.split("/")
        parent_dir = "/".join(parts[:-1])
        dir_name = parts[-1]
        
        if parent_dir not in tree_map:
            tree_map[parent_dir] = []
        
        tree_map[parent_dir].append(TreeEntry(
            "040000",
            dir_name,
            tree_sha1
        ))
    
    root_entries = tree_map.get("", [])
    root_tree_data = serialize_tree(root_entries)
    return hash_object(root_tree_data, "tree")


def tree_to_index(tree_sha1: str, base_path: str = "") -> Dict[str, Dict]:
    """
    根据 tree 对象递归展开为扁平的暂存区格式。
    
    Args:
        tree_sha1: tree 对象的 SHA-1
        base_path: 基准路径（内部递归使用）
    
    Returns:
        暂存区格式的字典
    """
    index = {}
    
    obj_type, content = read_object(tree_sha1)
    assert obj_type == "tree", f"Expected tree, got {obj_type}"
    
    entries = parse_tree(content)
    
    for entry in entries:
        full_path = os.path.join(base_path, entry.name).replace("\\", "/")
        
        if entry.mode == "040000":
            sub_index = tree_to_index(entry.sha1, full_path)
            index.update(sub_index)
        else:
            index[full_path] = {
                "mode": entry.mode,
                "sha1": entry.sha1
            }
    
    return index


def checkout_tree(tree_sha1: str) -> None:
    """
    根据 tree 对象恢复工作区文件。
    
    这是 checkout 的核心：将 tree 对象递归展开，把每个 blob
    的内容写入对应的工作区文件。
    
    **注意**: 这个函数会覆盖工作区文件，调用前应确保安全检查已通过。
    
    Args:
        tree_sha1: 根 tree 的 SHA-1
    """
    index = tree_to_index(tree_sha1)
    
    current_index = read_index()
    current_files = set(current_index.keys())
    new_files = set(index.keys())
    
    files_to_delete = current_files - new_files
    for file_path in files_to_delete:
        if os.path.exists(file_path):
            os.remove(file_path)
        _clean_empty_dirs(os.path.dirname(file_path))
    
    for file_path, entry in index.items():
        obj_type, content = read_object(entry["sha1"])
        assert obj_type == "blob", f"Expected blob for {file_path}, got {obj_type}"
        
        os.makedirs(os.path.dirname(file_path) or ".", exist_ok=True)
        
        with open(file_path, "wb") as f:
            f.write(content)
    
    write_index(index)


def _clean_empty_dirs(dir_path: str) -> None:
    """递归删除空目录"""
    if not dir_path or dir_path == "." or not os.path.isdir(dir_path):
        return
    
    try:
        if not os.listdir(dir_path):
            os.rmdir(dir_path)
            parent = os.path.dirname(dir_path)
            _clean_empty_dirs(parent)
    except OSError:
        pass


def get_status() -> Dict[str, List[str]]:
    """
    获取工作区状态（修改、新增、删除的文件）。
    
    Returns:
        包含 modified、added、deleted 列表的字典
    """
    index = read_index()
    status = {
        "modified": [],
        "added": [],
        "deleted": [],
        "staged_modified": [],
        "staged_added": [],
        "staged_deleted": []
    }
    
    head_commit = _get_head_commit_safe()
    head_tree = None
    head_index = {}
    
    if head_commit:
        from .objects import parse_commit
        commit_info = parse_commit(head_commit)
        head_tree = commit_info["tree"]
        head_index = tree_to_index(head_tree)
    
    for file_path, entry in index.items():
        if not os.path.exists(file_path):
            status["deleted"].append(file_path)
        else:
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                
                import hashlib
                header = f"blob {len(content)}\x00".encode("utf-8")
                store = header + content
                current_sha1 = hashlib.sha1(store).hexdigest()
                
                if current_sha1 != entry["sha1"]:
                    status["modified"].append(file_path)
            except Exception:
                pass
        
        if file_path not in head_index:
            status["staged_added"].append(file_path)
        elif head_index[file_path]["sha1"] != entry["sha1"]:
            status["staged_modified"].append(file_path)
    
    for file_path in head_index:
        if file_path not in index:
            status["staged_deleted"].append(file_path)
    
    _scan_working_dir(".", index, status)
    
    return status


def _scan_working_dir(dir_path: str, index: Dict[str, Dict], status: Dict) -> None:
    """扫描工作区，找出未跟踪的文件"""
    for entry in os.listdir(dir_path):
        full_path = os.path.join(dir_path, entry)
        rel_path = os.path.normpath(full_path).replace("\\", "/")
        
        if rel_path.startswith(GIT_DIR) or entry == GIT_DIR:
            continue
        
        if os.path.isdir(full_path):
            _scan_working_dir(full_path, index, status)
        elif os.path.isfile(full_path):
            if rel_path not in index:
                status["added"].append(rel_path)


def _get_head_commit_safe() -> Optional[str]:
    """安全地获取 HEAD commit，失败返回 None"""
    try:
        from .objects import get_head_commit
        return get_head_commit()
    except Exception:
        return None
