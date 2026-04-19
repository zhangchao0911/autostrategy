#!/usr/bin/env python3
"""
Autostrategy 环境检测与一键安装脚本

用法:
    python3 env_setup.py                  # 检测当前环境
    python3 env_setup.py --market A股     # 安装A股所需依赖
    python3 env_setup.py --market 港股    # 安装港股所需依赖
    python3 env_setup.py --market 美股    # 安装美股所需依赖
    python3 env_setup.py --install all    # 安装全部依赖
"""

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── 常量 ──────────────────────────────────────────────

SKILLS_DIRS = [
    Path.home() / ".claude" / ".agents" / "skills",  # npx skills add 安装路径
    Path.home() / ".claude" / "skills",               # 旧版路径
]
PYTHON = sys.executable

# 各市场所需 pip 包
MARKET_PACKAGES = {
    "A股": ["akshare", "backtrader", "pandas", "numpy", "matplotlib"],
    "港股": ["futu-api", "backtrader", "pandas", "numpy", "matplotlib"],
    "美股": ["futu-api", "backtrader", "pandas", "numpy", "matplotlib"],
}

# 通用依赖（所有市场都需要）
COMMON_PACKAGES = ["backtrader", "pandas", "numpy", "matplotlib", "pyyaml"]

# 各市场需要的 Skill
MARKET_SKILLS = {
    "A股": ["ftshare-all-in-one"],
    "港股": ["futuapi"],
    "美股": ["futuapi"],
}

# ── 工具函数 ──────────────────────────────────────────


def pip_install(packages: list[str]) -> dict[str, bool]:
    """批量安装 pip 包，返回 {包名: 是否成功}"""
    results = {}
    for pkg in packages:
        try:
            result = subprocess.run(
                [PYTHON, "-m", "pip", "install", pkg, "-q"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            success = result.returncode == 0
            results[pkg] = success
            if not success:
                print(f"  ✗ {pkg} 安装失败: {result.stderr.strip()[:100]}")
            else:
                print(f"  ✓ {pkg} 安装成功")
        except subprocess.TimeoutExpired:
            results[pkg] = False
            print(f"  ✗ {pkg} 安装超时")
    return results


IMPORT_MAP = {"futu-api": "futunn", "pyyaml": "yaml", "PyYAML": "yaml"}


def check_pip_package(package: str) -> dict:
    """检测单个 pip 包是否已安装"""
    try:
        mod_name = IMPORT_MAP.get(package, package.replace("-", "_"))
        mod = importlib.import_module(mod_name)
        version = getattr(mod, "__version__", "未知版本")
        return {"name": package, "installed": True, "version": version}
    except ImportError:
        return {"name": package, "installed": False, "version": None}


def check_all_packages(packages: list[str]) -> list[dict]:
    """检测多个 pip 包"""
    return [check_pip_package(pkg) for pkg in packages]


def check_skill_installed(skill_name: str) -> dict:
    """检测 Claude Code Skill 是否已安装（检查多个可能路径）"""
    for base_dir in SKILLS_DIRS:
        skill_dir = base_dir / skill_name
        if (skill_dir / "SKILL.md").exists():
            return {"name": skill_name, "installed": True, "path": str(skill_dir)}
    # 未找到，返回第一个候选路径用于提示
    return {"name": skill_name, "installed": False, "path": str(SKILLS_DIRS[0] / skill_name)}


def check_opend_running() -> dict:
    """检测 Futu OpenD 是否运行中"""
    try:
        result = subprocess.run(
            ["lsof", "-i", ":33333"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        running = result.returncode == 0 and "LISTEN" in result.stdout
        return {"running": running, "port": 33333}
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"running": False, "port": 33333}


def check_python_version() -> dict:
    """检测 Python 版本"""
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ok = sys.version_info >= (3, 9)
    return {"version": version, "ok": ok}


# ── 主流程 ──────────────────────────────────────────


def detect() -> dict:
    """全面检测当前环境"""
    env = {"python": check_python_version()}

    # 检测所有可能用到的 pip 包
    all_pkgs = set(COMMON_PACKAGES)
    for pkgs in MARKET_PACKAGES.values():
        all_pkgs.update(pkgs)
    env["packages"] = check_all_packages(sorted(all_pkgs))

    # 检测 Skill
    all_skills = set()
    for skills in MARKET_SKILLS.values():
        all_skills.update(skills)
    all_skills.add("futuapi")
    env["skills"] = [check_skill_installed(s) for s in sorted(all_skills)]

    # 检测 OpenD
    env["opend"] = check_opend_running()

    return env


def install(market: str = None) -> dict:
    """安装指定市场的依赖"""
    results = {"pip": {}, "skills": {}, "opend": False}

    # 确定 pip 包列表
    if market and market in MARKET_PACKAGES:
        packages = list(set(MARKET_PACKAGES[market] + COMMON_PACKAGES))
    else:
        packages = COMMON_PACKAGES

    print(f"\n📦 安装 pip 依赖 ({len(packages)} 个)...")
    results["pip"] = pip_install(packages)

    # 检查是否需要安装 Skill
    if market and market in MARKET_SKILLS:
        for skill_name in MARKET_SKILLS[market]:
            check = check_skill_installed(skill_name)
            if not check["installed"]:
                print(f"\n⚠️  Skill '{skill_name}' 未安装")
                print(f"   请在 Claude Code 中使用 /install-skill 或手动安装到: {check['path']}")

    # 检查是否需要 OpenD
    if market in ("港股", "美股"):
        opend = check_opend_running()
        if not opend["running"]:
            print(f"\n⚠️  Futu OpenD 未运行（端口 33333 无监听）")
            print("   请先启动 OpenD，或在 Claude Code 中使用 /install-futu-opend")

    return results


def print_report(env: dict):
    """打印环境检测报告"""
    print("=" * 50)
    print("  Autostrategy 环境检测报告")
    print("=" * 50)

    # Python
    py = env["python"]
    status = "✓" if py["ok"] else "✗"
    print(f"\n🐍 Python {py['version']} {status}")
    if not py["ok"]:
        print("   需要 Python 3.9+")

    # pip 包
    print(f"\n📦 已安装的包:")
    for pkg in env["packages"]:
        if pkg["installed"]:
            print(f"  ✓ {pkg['name']} ({pkg['version']})")
        else:
            print(f"  ✗ {pkg['name']} (未安装)")

    # Skills
    print(f"\n🧩 已安装的 Skill:")
    for skill in env["skills"]:
        if skill["installed"]:
            print(f"  ✓ {skill['name']}")
        else:
            print(f"  ✗ {skill['name']}")

    # OpenD
    opend = env["opend"]
    status = "✓ 运行中" if opend["running"] else "✗ 未运行"
    print(f"\n🔌 Futu OpenD: {status}")

    # 推荐
    print(f"\n💡 推荐命令:")
    missing_pkgs = [p["name"] for p in env["packages"] if not p["installed"]]
    if missing_pkgs:
        print(f"   python3 env_setup.py --install all")
    if not opend["running"]:
        print(f"   (如需港美股) 启动 Futu OpenD")

    print()


def main():
    parser = argparse.ArgumentParser(description="Autostrategy 环境检测与安装")
    parser.add_argument("--market", choices=["A股", "港股", "美股"],
                        help="目标市场")
    parser.add_argument("--install", choices=["all"] + ["A股", "港股", "美股"],
                        help="安装指定市场依赖 (all = 全部)")
    args = parser.parse_args()

    if args.install:
        market = args.install if args.install != "all" else args.market
        install(market)
        print("\n✅ 安装完成，重新检测环境...")
        env = detect()
        print_report(env)
    else:
        env = detect()
        print_report(env)

    # 输出 JSON 供 AI 解析
    json_path = Path(__file__).parent / "env_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
