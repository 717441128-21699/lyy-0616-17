"""核心命令实现 - init, add, commit, log, checkout"""

import os
import sys
from typing import Optional

from .objects import (
    GIT_DIR,
    OBJECTS_DIR,
    create_commit,
    get_head_commit,
    parse_commit,
    update_ref,
)
from .index import (
    add_file,
    checkout_tree,
    get_status,
    index_to_tree,
    read_index,
    tree_to_index,
    write_index,
)


def cmd_init() -> int:
    """
    初始化一个新的 pytig 仓库。
    
    创建 .pytig 目录结构：
        .pytig/
            objects/    # 对象存储
            refs/heads/ # 分支引用
            HEAD        # 当前 HEAD 指针
            index       # 暂存区（初始不存在）
    """
    if os.path.exists(GIT_DIR):
        print(f"已存在 {GIT_DIR} 目录，重新初始化中...")
    
    os.makedirs(OBJECTS_DIR, exist_ok=True)
    os.makedirs(os.path.join(GIT_DIR, "refs", "heads"), exist_ok=True)
    
    head_path = os.path.join(GIT_DIR, "HEAD")
    with open(head_path, "w") as f:
        f.write("ref: refs/heads/main\n")
    
    print(f"已初始化空的 pytig 仓库于 {os.path.abspath(GIT_DIR)}/")
    return 0


def cmd_add(paths: list) -> int:
    """
    将文件添加到暂存区。
    
    Args:
        paths: 文件路径列表
    
    Returns:
        退出码
    """
    if not os.path.exists(GIT_DIR):
        print("错误：不是 pytig 仓库（请先运行 pytig init）", file=sys.stderr)
        return 1
    
    for path in paths:
        if os.path.isdir(path):
            _add_directory(path)
        elif os.path.isfile(path):
            try:
                add_file(path)
                print(f"add '{path}'")
            except Exception as e:
                print(f"错误：{e}", file=sys.stderr)
                return 1
        else:
            print(f"警告：路径不存在 - {path}", file=sys.stderr)
    
    return 0


def _add_directory(dir_path: str) -> None:
    """递归添加目录下的所有文件"""
    for root, dirs, files in os.walk(dir_path):
        if GIT_DIR in dirs:
            dirs.remove(GIT_DIR)
        
        for file in files:
            full_path = os.path.join(root, file)
            add_file(full_path)
            print(f"add '{full_path}'")


def cmd_commit(message: str, allow_empty: bool = False) -> int:
    """
    创建一个新的提交。
    
    commit 工作流程：
    1. 将暂存区转换为 tree 对象
    2. 获取当前 HEAD 作为父提交
    3. 创建 commit 对象（记录 tree、parent、message 等）
    4. 更新 HEAD 和分支引用指向新的 commit
    
    **父提交形成历史链**：
    每个 commit 对象都记录了它的父提交 SHA-1（初始提交除外）。
    通过不断追溯 parent，就能形成一条完整的提交历史链。
    这就是 Git 的"有向无环图"（DAG）提交历史的基础。
    
    Args:
        message: 提交信息
        allow_empty: 是否允许空提交（暂存区无变化也提交）
    
    Returns:
        退出码
    """
    if not os.path.exists(GIT_DIR):
        print("错误：不是 pytig 仓库", file=sys.stderr)
        return 1
    
    index = read_index()
    if not index and not allow_empty:
        print("错误：暂存区为空，没有什么可提交的", file=sys.stderr)
        return 1
    
    tree_sha1 = index_to_tree()
    
    parent_sha1 = get_head_commit()
    
    if parent_sha1:
        parent_commit = parse_commit(parent_sha1)
        if parent_commit["tree"] == tree_sha1 and not allow_empty:
            print("没有什么可提交的，工作区是干净的")
            return 0
    
    commit_sha1 = create_commit(tree_sha1, parent_sha1, message)
    
    _update_head(commit_sha1)
    
    short_sha = commit_sha1[:7]
    if parent_sha1:
        print(f"[main {short_sha}] {message.split(chr(10))[0]}")
    else:
        print(f"[main (root-commit) {short_sha}] {message.split(chr(10))[0]}")
    
    return 0


def _update_head(commit_sha1: str) -> None:
    """更新 HEAD 指向的引用"""
    head_path = os.path.join(GIT_DIR, "HEAD")
    with open(head_path, "r") as f:
        ref = f.read().strip()
    
    if ref.startswith("ref: "):
        ref_name = ref[5:]
        update_ref(ref_name, commit_sha1)
    else:
        with open(head_path, "w") as f:
            f.write(commit_sha1 + "\n")


def cmd_log(max_count: int = 10, oneline: bool = False) -> int:
    """
    显示提交历史。
    
    从 HEAD 开始，沿着 parent 链回溯，打印每个提交的信息。
    这展示了 commit 如何通过父提交引用形成历史链。
    
    Args:
        max_count: 最多显示多少条提交
        oneline: 是否以单行简洁模式显示
    
    Returns:
        退出码
    """
    if not os.path.exists(GIT_DIR):
        print("错误：不是 pytig 仓库", file=sys.stderr)
        return 1
    
    head_sha1 = get_head_commit()
    if not head_sha1:
        print("当前没有任何提交")
        return 0
    
    current = head_sha1
    count = 0
    
    while current and count < max_count:
        try:
            commit = parse_commit(current)
        except FileNotFoundError:
            break
        
        if oneline:
            short_sha = current[:7]
            first_line = commit["message"].split("\n")[0]
            if count > 0:
                print()
            print(f"{short_sha} {first_line}")
        else:
            if count > 0:
                print()
            print(f"commit {current}")
            print(f"Author: {_format_author(commit['author'])}")
            print(f"Date:   {_format_date(commit['author'])}")
            print()
            for line in commit["message"].split("\n"):
                print(f"    {line}")
        
        parents = commit["parents"]
        if parents:
            current = parents[0]
        else:
            break
        
        count += 1
    
    return 0


def _format_author(author_line: str) -> str:
    """从 author 行提取作者信息"""
    parts = author_line.rsplit(" ", 2)
    return parts[0] if len(parts) >= 3 else author_line


def _format_date(author_line: str) -> str:
    """从 author 行提取并格式化日期"""
    import datetime
    parts = author_line.rsplit(" ", 2)
    if len(parts) >= 2:
        try:
            timestamp = int(parts[-2])
            dt = datetime.datetime.fromtimestamp(timestamp)
            return dt.strftime("%a %b %d %H:%M:%S %Y")
        except (ValueError, IndexError):
            pass
    return ""


def cmd_checkout(commit_ref: str, force: bool = False) -> int:
    """
    切换到指定的提交。
    
    **checkout 时处理未提交修改的策略选择**：
    
    我们选择的策略：**默认拒绝（安全第一），提供 --force 选项强制覆盖**。
    
    理由：
    1. **数据安全优先**：未提交的修改是用户的工作成果，如果被静默覆盖
       会造成不可逆的数据丢失。这是 Git 的设计哲学。
    2. **用户明确意图**：只有用户明确指定 --force 时才覆盖，确保用户
       知道自己在做什么。
    3. **其他方案的问题**：
       - 直接覆盖：太危险，容易造成意外数据丢失
       - 尝试合并：实现复杂，且合并冲突对用户不友好；真正的合并
         应该用 merge 命令显式进行
       - 自动暂存（git stash）：增加了复杂性，且用户可能不理解
         自动操作的含义
    
    所以我们采用 Git 默认的保守策略：有未提交修改时拒绝切换，
    由用户决定如何处理（提交、丢弃还是强制切换）。
    
    工作流程：
    1. 解析目标提交引用（可以是完整 SHA-1 或短 SHA-1）
    2. 检查工作区是否有未提交的修改
    3. 如果有修改且没有 --force，拒绝切换并给出提示
    4. 如果允许切换，更新工作区和暂存区到目标提交的状态
    5. 更新 HEAD 指向目标提交
    
    Args:
        commit_ref: 提交引用（SHA-1 或短 SHA-1）
        force: 是否强制切换（忽略未提交的修改）
    
    Returns:
        退出码
    """
    if not os.path.exists(GIT_DIR):
        print("错误：不是 pytig 仓库", file=sys.stderr)
        return 1
    
    commit_sha1 = _resolve_ref(commit_ref)
    if not commit_sha1:
        print(f"错误：找不到提交 '{commit_ref}'", file=sys.stderr)
        return 1
    
    try:
        commit = parse_commit(commit_sha1)
    except Exception as e:
        print(f"错误：无效的提交 - {e}", file=sys.stderr)
        return 1
    
    if not force:
        status = get_status()
        has_changes = (
            status["modified"] or
            status["deleted"] or
            status["staged_modified"] or
            status["staged_added"] or
            status["staged_deleted"]
        )
        
        if has_changes:
            print("错误：您有未提交的修改，无法切换分支/提交。", file=sys.stderr)
            print("请先提交您的修改，或者使用 --force 强制切换（会丢弃修改）。", file=sys.stderr)
            print()
            print("未提交的修改：")
            if status["staged_modified"]:
                for f in status["staged_modified"]:
                    print(f"  已暂存修改: {f}")
            if status["staged_added"]:
                for f in status["staged_added"]:
                    print(f"  已暂存新增: {f}")
            if status["staged_deleted"]:
                for f in status["staged_deleted"]:
                    print(f"  已暂存删除: {f}")
            if status["modified"]:
                for f in status["modified"]:
                    print(f"  未暂存修改: {f}")
            if status["deleted"]:
                for f in status["deleted"]:
                    print(f"  未暂存删除: {f}")
            return 1
    
    tree_sha1 = commit["tree"]
    checkout_tree(tree_sha1)
    
    head_path = os.path.join(GIT_DIR, "HEAD")
    with open(head_path, "w") as f:
        f.write(commit_sha1 + "\n")
    
    short_sha = commit_sha1[:7]
    print(f"HEAD 现在位于 {short_sha} {commit['message'].split(chr(10))[0]}")
    
    return 0


def _resolve_ref(ref: str) -> Optional[str]:
    """
    解析引用为完整的 SHA-1。
    
    支持：
    - 完整的 40 位 SHA-1
    - 短 SHA-1（至少 4 位）
    - 分支名（简化处理）
    
    Args:
        ref: 引用字符串
    
    Returns:
        完整的 SHA-1 字符串，找不到返回 None
    """
    import glob
    
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref.lower()):
        return ref
    
    if len(ref) >= 4 and all(c in "0123456789abcdef" for c in ref.lower()):
        prefix = ref[:2]
        suffix = ref[2:]
        obj_dir = os.path.join(OBJECTS_DIR, prefix)
        if os.path.isdir(obj_dir):
            matches = [f for f in os.listdir(obj_dir) if f.startswith(suffix)]
            if len(matches) == 1:
                return prefix + matches[0]
            elif len(matches) > 1:
                print(f"错误：短 SHA-1 '{ref}' 不明确，有多个匹配", file=sys.stderr)
                return None
    
    branch_ref = os.path.join(GIT_DIR, "refs", "heads", ref)
    if os.path.isfile(branch_ref):
        with open(branch_ref, "r") as f:
            return f.read().strip()
    
    return None


def cmd_status() -> int:
    """显示工作区状态"""
    if not os.path.exists(GIT_DIR):
        print("错误：不是 pytig 仓库", file=sys.stderr)
        return 1
    
    head_sha1 = get_head_commit()
    if head_sha1:
        print(f"位于提交 {head_sha1[:7]}")
    else:
        print("当前没有提交")
    
    status = get_status()
    
    staged = status["staged_modified"] + status["staged_added"] + status["staged_deleted"]
    if staged:
        print()
        print("要提交的变更：")
        print("  （使用 \"pytig reset HEAD <file>...\" 取消暂存）")
        print()
        for f in status["staged_added"]:
            print(f"\t新文件：   {f}")
        for f in status["staged_modified"]:
            print(f"\t修改：     {f}")
        for f in status["staged_deleted"]:
            print(f"\t删除：     {f}")
    
    unstaged = status["modified"] + status["deleted"]
    if unstaged:
        print()
        print("未暂存的变更：")
        print("  （使用 \"pytig add <file>...\" 更新要提交的内容）")
        print()
        for f in status["modified"]:
            print(f"\t修改：     {f}")
        for f in status["deleted"]:
            print(f"\t删除：     {f}")
    
    if status["added"]:
        print()
        print("未跟踪的文件：")
        print("  （使用 \"pytig add <file>...\" 包含在要提交的内容中）")
        print()
        for f in status["added"]:
            print(f"\t{f}")
    
    if not staged and not unstaged and not status["added"]:
        print()
        print("没有什么可提交的，工作区是干净的")
    
    return 0
