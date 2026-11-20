#!/usr/bin/env python3
"""
检测并修复 machine/ 目录下指向 machine/pcb/ 的符号链接。

主要处理场景：
  1) 本应是符号链接，却被检出为普通文件（内容为一行路径字符串）
     —— 最常见于 Windows 上 clone 时未启用 core.symlinks
  2) 指向 machine/pcb/ 的普通文件，内容指向不存在的目标（仅报告，不自动改）

用法:
  python fix_symlinks.py                 # 真正修复
  python fix_symlinks.py --dry-run       # 只看不修
  python fix_symlinks.py --root machine  # 自定义扫描根目录

退出码:
  0 全部 OK
  1 存在需人工处理的项
  2 参数/环境错误
"""

import argparse
import os
import sys
from pathlib import Path

PATH_MAX_BYTES = 4096


def looks_like_path(content: bytes):
    """如果内容看起来是一行路径字符串，返回去换行后的字符串；否则 None。"""
    if not content or len(content) > PATH_MAX_BYTES:
        return None
    if b"\x00" in content:
        return None
    text = content.rstrip(b"\r\n")
    if not text or b"\n" in text or b"\r" in text:
        return None
    try:
        s = text.decode("utf-8")
    except UnicodeDecodeError:
        return None
    s = s.strip()
    if not s:
        return None
    if any(ord(c) < 0x20 for c in s):
        return None
    return s


def resolve_target(link_path: Path, raw: str) -> Path:
    """把 raw 解析为绝对路径（相对于 link_path 所在目录），允许目标不存在。"""
    # 兼容可能出现的 Windows 风格反斜杠
    normalized = raw.replace("\\", "/")
    p = Path(normalized)
    if p.is_absolute():
        return p.resolve(strict=False)
    return (link_path.parent / p).resolve(strict=False)


def is_inside(target: Path, root: Path) -> bool:
    try:
        target.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def scan(machine_dir: Path, pcb_dir: Path):
    findings = []
    pcb_resolved = pcb_dir.resolve(strict=False)

    for dirpath, dirnames, filenames in os.walk(machine_dir, followlinks=False):
        cur = Path(dirpath)
        # 跳过 .git 和 pcb 目录本身
        dirnames[:] = [
            d for d in dirnames
            if d != ".git" and (cur / d).resolve(strict=False) != pcb_resolved
        ]

        for name in filenames:
            p = cur / name
            if p.is_symlink():
                raw = os.readlink(p)
                target = resolve_target(p, raw)
                if not is_inside(target, pcb_dir):
                    continue
                if target.exists():
                    findings.append(("ok", p, raw, target))
                else:
                    findings.append(("broken", p, raw, target))
            elif p.is_file():
                try:
                    content = p.read_bytes()
                except OSError as e:
                    print(f"[warn] 无法读取 {p}: {e}", file=sys.stderr)
                    continue
                raw = looks_like_path(content)
                if raw is None:
                    continue
                target = resolve_target(p, raw)
                if not is_inside(target, pcb_dir):
                    continue
                if target.exists():
                    findings.append(("plain", p, raw, target))
                else:
                    findings.append(("plain_bad", p, raw, target))
    return findings


def repair(item, dry_run: bool) -> bool:
    kind, path, raw, target = item
    prefix = "[dry-run]" if dry_run else "[fix]"

    if kind == "ok":
        return False
    if kind == "broken":
        print(f"[warn]    断裂符号链接（目标不存在，需人工确认）: {path} -> {raw!r} (解析为 {target})")
        return False
    if kind == "plain_bad":
        print(f"[warn]    普通文件指向不存在的目标，需人工确认: {path} 内容={raw!r} 解析为 {target}")
        return False
    if kind == "plain":
        print(f"{prefix}     普通文件 -> 符号链接: {path} -> {raw!r}")
        if dry_run:
            return True
        try:
            path.unlink()
            os.symlink(raw, path, target_is_directory=target.is_dir())
            return True
        except OSError as e:
            print(f"[error]   {path}: {e}", file=sys.stderr)
            if os.name == "nt" and getattr(e, "winerror", None) == 1314:
                print("          提示: Windows 上创建符号链接需要管理员权限或开发者模式", file=sys.stderr)
            return False
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="检测并修复 machine/ 下指向 machine/pcb/ 的符号链接")
    ap.add_argument("--root", default="machine", help="扫描根目录（默认 machine）")
    ap.add_argument("--pcb", default=None, help="pcb 目录（默认 <root>/pcb）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不修改")
    args = ap.parse_args()

    root = Path(args.root)
    pcb = Path(args.pcb) if args.pcb else root / "pcb"

    if not root.is_dir():
        print(f"[error] 根目录不存在: {root}", file=sys.stderr)
        return 2
    if not pcb.is_dir():
        print(f"[error] pcb 目录不存在: {pcb}", file=sys.stderr)
        return 2

    print(f"扫描 {root}/，目标 pcb 目录: {pcb}/")
    findings = scan(root, pcb)

    stats = {"ok": 0, "broken": 0, "plain": 0, "plain_bad": 0, "fixed": 0}
    for item in findings:
        stats[item[0]] += 1
        if repair(item, args.dry_run):
            stats["fixed"] += 1

    print()
    print("== 汇总 ==")
    print(f"  有效符号链接:       {stats['ok']}")
    print(f"  断裂符号链接:       {stats['broken']}")
    print(f"  普通文件(应转链接): {stats['plain']}")
    print(f"  普通文件(坏目标):   {stats['plain_bad']}")
    print(f"  已修复:             {stats['fixed']}")
    return 0 if stats["plain_bad"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())