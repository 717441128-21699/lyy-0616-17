"""pytig 命令行主入口"""

import argparse
import sys

from .commands import (
    cmd_add,
    cmd_checkout,
    cmd_commit,
    cmd_init,
    cmd_log,
    cmd_status,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pytig",
        description="一个简化版的 Git 实现（用 Python 编写）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
支持的命令：
  init       初始化一个新的仓库
  add        将文件添加到暂存区
  commit     提交暂存区的内容
  log        查看提交历史
  checkout   切换到指定提交
  status     显示工作区状态
        """.strip()
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用的命令")
    
    subparsers.add_parser("init", help="初始化一个新的 pytig 仓库")
    
    add_parser = subparsers.add_parser("add", help="将文件添加到暂存区")
    add_parser.add_argument("paths", nargs="+", help="要添加的文件或目录路径")
    
    commit_parser = subparsers.add_parser("commit", help="提交暂存区的内容")
    commit_parser.add_argument("-m", "--message", required=True, help="提交信息")
    commit_parser.add_argument("--allow-empty", action="store_true", 
                               help="允许空提交（暂存区无变化也提交）")
    
    log_parser = subparsers.add_parser("log", help="查看提交历史")
    log_parser.add_argument("-n", "--max-count", type=int, default=10, 
                            help="最多显示多少条提交")
    log_parser.add_argument("--oneline", action="store_true", 
                            help="以单行简洁模式显示")
    
    checkout_parser = subparsers.add_parser("checkout", help="切换到指定提交")
    checkout_parser.add_argument("commit", help="提交 SHA-1 或引用")
    checkout_parser.add_argument("-f", "--force", action="store_true",
                                 help="强制切换，丢弃未提交的修改")
    
    subparsers.add_parser("status", help="显示工作区状态")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    try:
        if args.command == "init":
            return cmd_init()
        elif args.command == "add":
            return cmd_add(args.paths)
        elif args.command == "commit":
            return cmd_commit(args.message, args.allow_empty)
        elif args.command == "log":
            return cmd_log(args.max_count, args.oneline)
        elif args.command == "checkout":
            return cmd_checkout(args.commit, args.force)
        elif args.command == "status":
            return cmd_status()
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print()
        return 130
    except Exception as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
