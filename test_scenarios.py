"""自动化验收脚本 - 覆盖三个核心场景"""

import os
import shutil
import subprocess
import sys
import tempfile

PYTIG = [sys.executable, "-m", "pytig"]
PASS = 0
FAIL = 0


def run(args, cwd, expect_fail=False):
    result = subprocess.run(
        PYTIG + args, cwd=cwd, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.abspath(__file__))}
    )
    if expect_fail:
        if result.returncode == 0:
            report("FAIL", args, "expected non-zero exit but got 0")
            return result
    else:
        if result.returncode != 0:
            report("FAIL", args, f"exit code {result.returncode}\nstderr: {result.stderr}")
            return result
    report("PASS", args, result.stdout.strip().split("\n")[0] if result.stdout.strip() else "")
    return result


def report(status, args, detail):
    global PASS, FAIL
    tag = f"[{status}]"
    cmd = " ".join(args)
    if status == "PASS":
        PASS += 1
        print(f"  {tag} pytig {cmd}")
    else:
        FAIL += 1
        print(f"  {tag} pytig {cmd} -- {detail}")


def make_repo():
    td = tempfile.mkdtemp(prefix="pytig_test_")
    run(["init"], td)
    return td


def cleanup(td):
    shutil.rmtree(td, ignore_errors=True)


def write_file(base, path, content):
    full = os.path.join(base, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


def read_file(base, path):
    with open(os.path.join(base, path), "r", encoding="utf-8") as f:
        return f.read()


def file_exists(base, path):
    return os.path.isfile(os.path.join(base, path))


def get_shas(stdout_text):
    shas = []
    for line in stdout_text.strip().split("\n"):
        if line.strip():
            sha = line.strip().split()[0]
            shas.append(sha)
    return shas


def test_deep_directory():
    print("\n=== 场景1: 多级目录提交 + checkout 恢复整条目录链 ===")
    td = make_repo()
    try:
        write_file(td, "src/lib/math/add.py", "def add(a, b): return a + b\n")
        write_file(td, "src/lib/sub.py", "def sub(a, b): return a - b\n")
        write_file(td, "tools/add.py", "def add(a, b): return a + b\n")
        write_file(td, "readme.txt", "v1\n")

        run(["add", "."], td)
        r = run(["commit", "-m", "Add deep dirs"], td)
        assert "(root-commit)" in r.stdout, "should be root commit"

        r = run(["log", "--oneline"], td)
        shas = get_shas(r.stdout)
        first_sha = shas[0]

        write_file(td, "readme.txt", "v2\n")
        shutil.rmtree(os.path.join(td, "src"))
        run(["add", "."], td)
        run(["commit", "-m", "Remove src, update readme"], td)

        assert not file_exists(td, "src/lib/math/add.py"), "src should be gone"
        assert not os.path.isdir(os.path.join(td, "src")), "src dir should be gone"

        run(["checkout", first_sha], td)

        assert file_exists(td, "src/lib/math/add.py"), "src/lib/math/add.py should be restored"
        assert file_exists(td, "src/lib/sub.py"), "src/lib/sub.py should be restored"
        assert file_exists(td, "tools/add.py"), "tools/add.py should be restored"
        assert file_exists(td, "readme.txt"), "readme.txt should exist"
        assert read_file(td, "src/lib/math/add.py") == "def add(a, b): return a + b\n", "content should match"
        assert read_file(td, "tools/add.py") == "def add(a, b): return a + b\n", "same content dedup"
        assert read_file(td, "readme.txt") == "v1\n", "readme should be v1"

        print("  >>> 场景1 全部通过 <<<")
    finally:
        cleanup(td)


def test_untracked_conflict():
    print("\n=== 场景2: 未跟踪同名文件冲突，默认拒绝 ===")
    td = make_repo()
    try:
        write_file(td, "hello.txt", "committed\n")
        write_file(td, "src/lib/math/add.py", "def add(a, b): return a + b\n")
        run(["add", "."], td)
        run(["commit", "-m", "Commit1: hello + deep file"], td)

        r = run(["log", "--oneline"], td)
        first_sha = get_shas(r.stdout)[0]

        shutil.rmtree(os.path.join(td, "src"))
        write_file(td, "hello.txt", "v2\n")
        run(["add", "."], td)
        run(["commit", "-m", "Commit2: remove src, update hello"], td)

        r = run(["log", "--oneline"], td)
        second_sha = get_shas(r.stdout)[0]

        run(["checkout", first_sha], td)
        assert file_exists(td, "src/lib/math/add.py")

        run(["checkout", second_sha], td)
        assert not file_exists(td, "src/lib/math/add.py"), "src should be gone"
        assert not os.path.isdir(os.path.join(td, "src")), "src dir should be gone"

        write_file(td, "src/lib/math/add.py", "my local notes\n")
        assert not file_exists_in_index(td, "src/lib/math/add.py"), "should NOT be in index"

        r = run(["checkout", first_sha], td, expect_fail=True)
        assert "src/lib/math/add.py" in r.stderr, "should mention untracked conflict"
        assert read_file(td, "src/lib/math/add.py") == "my local notes\n", "local file not overwritten"

        print("  >>> 场景2 全部通过 <<<")
    finally:
        cleanup(td)


def file_exists_in_index(td, path):
    idx = os.path.join(td, ".pytig", "index")
    if not os.path.isfile(idx):
        return False
    with open(idx, "r", encoding="utf-8") as f:
        for line in f:
            if path in line:
                return True
    return False


def test_force_override():
    print("\n=== 场景3: --force 强制覆盖未跟踪同名文件 ===")
    td = make_repo()
    try:
        write_file(td, "hello.txt", "committed\n")
        write_file(td, "src/lib/math/add.py", "def add(a, b): return a + b\n")
        run(["add", "."], td)
        run(["commit", "-m", "Commit1: hello + deep file"], td)

        r = run(["log", "--oneline"], td)
        first_sha = get_shas(r.stdout)[0]

        shutil.rmtree(os.path.join(td, "src"))
        write_file(td, "hello.txt", "v2\n")
        run(["add", "."], td)
        run(["commit", "-m", "Commit2: remove src, update hello"], td)

        r = run(["log", "--oneline"], td)
        second_sha = get_shas(r.stdout)[0]

        run(["checkout", second_sha], td)

        write_file(td, "src/lib/math/add.py", "my local notes\n")

        run(["checkout", first_sha, "--force"], td)

        assert read_file(td, "src/lib/math/add.py") == "def add(a, b): return a + b\n", "should be overwritten by commit content"
        assert read_file(td, "hello.txt") == "committed\n", "hello should be v1 from commit1"

        print("  >>> 场景3 全部通过 <<<")
    finally:
        cleanup(td)


if __name__ == "__main__":
    print("=" * 60)
    print("pytig 自动化验收")
    print("=" * 60)
    test_deep_directory()
    test_untracked_conflict()
    test_force_override()
    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)
