"""对象存储模块 - 实现内容寻址的 blob、tree、commit 对象"""

import hashlib
import os
import zlib
from pathlib import Path
from typing import List, Optional, Tuple


GIT_DIR = ".pytig"
OBJECTS_DIR = os.path.join(GIT_DIR, "objects")


def hash_object(data: bytes, obj_type: str = "blob", write: bool = True) -> str:
    """
    计算对象的 SHA-1 哈希，并可选地写入对象存储。
    
    对象格式: <type> SPACE <size> NUL <content>
    
    Args:
        data: 对象内容（字节）
        obj_type: 对象类型 (blob, tree, commit)
        write: 是否写入对象存储
    
    Returns:
        对象的 SHA-1 哈希字符串
    """
    header = f"{obj_type} {len(data)}\x00".encode("utf-8")
    store = header + data
    sha1 = hashlib.sha1(store).hexdigest()

    if write:
        obj_dir = os.path.join(OBJECTS_DIR, sha1[:2])
        obj_path = os.path.join(obj_dir, sha1[2:])
        if not os.path.exists(obj_path):
            os.makedirs(obj_dir, exist_ok=True)
            compressed = zlib.compress(store)
            with open(obj_path, "wb") as f:
                f.write(compressed)

    return sha1


def read_object(sha1: str) -> Tuple[str, bytes]:
    """
    从对象存储中读取对象。
    
    Args:
        sha1: 对象的 SHA-1 哈希
    
    Returns:
        (对象类型, 对象内容字节) 元组
    
    Raises:
        FileNotFoundError: 如果对象不存在
    """
    obj_path = os.path.join(OBJECTS_DIR, sha1[:2], sha1[2:])
    with open(obj_path, "rb") as f:
        compressed = f.read()
    
    store = zlib.decompress(compressed)
    
    nul_idx = store.index(b"\x00")
    header = store[:nul_idx].decode("utf-8")
    obj_type, size_str = header.split(" ", 1)
    content = store[nul_idx + 1:]
    
    assert len(content) == int(size_str), f"Object size mismatch for {sha1}"
    
    return obj_type, content


def create_blob(file_path: str) -> str:
    """
    为文件创建 blob 对象。
    
    Args:
        file_path: 文件路径
    
    Returns:
        blob 对象的 SHA-1 哈希
    """
    with open(file_path, "rb") as f:
        data = f.read()
    return hash_object(data, "blob")


class TreeEntry:
    """Tree 对象中的条目"""
    
    def __init__(self, mode: str, name: str, sha1: str):
        self.mode = mode  # "100644" for regular file, "040000" for directory
        self.name = name
        self.sha1 = sha1
    
    def __repr__(self) -> str:
        return f"TreeEntry({self.mode} {self.name} {self.sha1[:7]}...)"


def parse_tree(content: bytes) -> List[TreeEntry]:
    """
    解析 tree 对象的内容。
    
    tree 格式: 每条目为 <mode> SPACE <name> NUL <20-byte sha1>
    
    Args:
        content: tree 对象的内容字节
    
    Returns:
        TreeEntry 列表（已按名称排序）
    """
    entries = []
    i = 0
    while i < len(content):
        space_idx = content.index(b" ", i)
        mode = content[i:space_idx].decode("utf-8")
        
        nul_idx = content.index(b"\x00", space_idx)
        name = content[space_idx + 1:nul_idx].decode("utf-8")
        
        sha1_bytes = content[nul_idx + 1:nul_idx + 21]
        sha1 = sha1_bytes.hex()
        
        entries.append(TreeEntry(mode, name, sha1))
        i = nul_idx + 21
    
    entries.sort(key=lambda e: e.name)
    return entries


def serialize_tree(entries: List[TreeEntry]) -> bytes:
    """
    将 TreeEntry 列表序列化为 tree 对象内容。
    
    Args:
        entries: TreeEntry 列表
    
    Returns:
        序列化后的字节
    """
    entries.sort(key=lambda e: e.name)
    result = b""
    for entry in entries:
        result += f"{entry.mode} {entry.name}\x00".encode("utf-8")
        result += bytes.fromhex(entry.sha1)
    return result


def create_tree_from_dir(dir_path: str, base_path: Optional[str] = None) -> str:
    """
    递归地为目录创建 tree 对象。
    
    **Tree 对象递归表达目录结构**:
    每个 tree 对象代表一个目录，包含多个条目。每个条目可以是：
    - 一个 blob（文件），mode 为 100644
    - 一个 tree（子目录），mode 为 040000
    
    通过这种递归方式，任意深度的目录结构都可以用树状的 tree 对象
    网络来表达，根 tree 代表整个项目根目录。
    
    **相同内容的文件天然去重**:
    因为对象存储是内容寻址的（用内容的 SHA-1 哈希作为文件名），
    如果两个文件内容完全相同，它们会生成相同的 blob 对象，
    在对象存储中只保存一份。这就是 Git 的"天然去重"特性。
    
    同样，如果两个子目录内容完全相同，它们的 tree 哈希也相同，
    也会共享同一个 tree 对象。
    
    Args:
        dir_path: 目录路径
        base_path: 基准路径（内部递归使用）
    
    Returns:
        tree 对象的 SHA-1 哈希
    """
    if base_path is None:
        base_path = dir_path
    
    entries = []
    
    for entry in sorted(os.listdir(dir_path)):
        full_path = os.path.join(dir_path, entry)
        rel_path = os.path.relpath(full_path, base_path)
        
        if os.path.isdir(full_path):
            if entry == GIT_DIR:
                continue
            sub_tree_sha1 = create_tree_from_dir(full_path, base_path)
            entries.append(TreeEntry("040000", entry, sub_tree_sha1))
        elif os.path.isfile(full_path):
            blob_sha1 = create_blob(full_path)
            entries.append(TreeEntry("100644", entry, blob_sha1))
    
    tree_data = serialize_tree(entries)
    return hash_object(tree_data, "tree")


def create_commit(tree_sha1: str, parent_sha1: Optional[str], 
                  message: str, author: str = "pytig user <user@pytig.local>") -> str:
    """
    创建 commit 对象。
    
    commit 格式:
        tree <tree_sha1>
        parent <parent_sha1>  (可省略，初始提交无父提交)
        author <author_info>
        committer <committer_info>
        
        <commit message>
    
    Args:
        tree_sha1: 根 tree 的 SHA-1
        parent_sha1: 父提交的 SHA-1（初始提交为 None）
        message: 提交信息
        author: 作者信息
    
    Returns:
        commit 对象的 SHA-1 哈希
    """
    import time
    
    timestamp = int(time.time())
    tz_offset = "+0800"
    
    lines = []
    lines.append(f"tree {tree_sha1}")
    if parent_sha1:
        lines.append(f"parent {parent_sha1}")
    lines.append(f"author {author} {timestamp} {tz_offset}")
    lines.append(f"committer {author} {timestamp} {tz_offset}")
    lines.append("")
    lines.append(message)
    
    commit_data = "\n".join(lines).encode("utf-8")
    return hash_object(commit_data, "commit")


def parse_commit(sha1: str) -> dict:
    """
    解析 commit 对象。
    
    Args:
        sha1: commit 的 SHA-1
    
    Returns:
        包含 commit 信息的字典
    """
    obj_type, content = read_object(sha1)
    assert obj_type == "commit", f"Expected commit, got {obj_type}"
    
    text = content.decode("utf-8")
    lines = text.split("\n")
    
    result = {
        "tree": None,
        "parents": [],
        "author": None,
        "committer": None,
        "message": ""
    }
    
    i = 0
    while i < len(lines) and lines[i] != "":
        line = lines[i]
        key, value = line.split(" ", 1)
        if key == "tree":
            result["tree"] = value
        elif key == "parent":
            result["parents"].append(value)
        elif key == "author":
            result["author"] = value
        elif key == "committer":
            result["committer"] = value
        i += 1
    
    i += 1
    if i < len(lines):
        result["message"] = "\n".join(lines[i:]).rstrip("\n")
    
    return result


def get_head_commit() -> Optional[str]:
    """获取 HEAD 指向的 commit SHA-1，如果没有则返回 None"""
    head_path = os.path.join(GIT_DIR, "HEAD")
    if not os.path.exists(head_path):
        return None
    
    with open(head_path, "r") as f:
        ref = f.read().strip()
    
    if ref.startswith("ref: "):
        ref_path = os.path.join(GIT_DIR, ref[5:])
        if not os.path.exists(ref_path):
            return None
        with open(ref_path, "r") as f:
            return f.read().strip()
    else:
        return ref


def update_ref(ref_name: str, sha1: str) -> None:
    """更新引用指向的 commit"""
    ref_path = os.path.join(GIT_DIR, ref_name)
    os.makedirs(os.path.dirname(ref_path), exist_ok=True)
    with open(ref_path, "w") as f:
        f.write(sha1 + "\n")


def cat_file(sha1: str) -> None:
    """显示对象的内容（调试用）"""
    obj_type, content = read_object(sha1)
    print(f"type: {obj_type}")
    print(f"size: {len(content)}")
    print("---")
    if obj_type == "tree":
        entries = parse_tree(content)
        for entry in entries:
            print(f"{entry.mode} {entry.sha1}    {entry.name}")
    elif obj_type == "commit":
        print(content.decode("utf-8"))
    else:
        try:
            print(content.decode("utf-8"))
        except UnicodeDecodeError:
            print(f"[binary data, {len(content)} bytes]")
