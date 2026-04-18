#!/usr/bin/env python3
"""
Autostrategy 策略文档质量检查脚本

检查 STRATEGY_DESIGN.md 是否满足可执行回测的最低质量标准。
类比 nuwa-skill 的 quality_check.py。

用法:
    python3 quality_check.py <STRATEGY_DESIGN.md路径>
    python3 quality_check.py ~/策略研究/双均线/STRATEGY_DESIGN.md

退出码:
    0 = 全部通过
    1 = 有检查项未通过
"""

import re
import sys
from pathlib import Path


# ── 检查项定义 ──────────────────────────────────────

CHECKS = [
    {
        "id": "completeness",
        "name": "文档完整性",
        "weight": 20,
        "desc": "必须包含所有核心 section",
    },
    {
        "id": "no_placeholder",
        "name": "无残留占位符",
        "weight": 20,
        "desc": "不能有 [需用户确认] 或 [X] 等未填充的占位符",
    },
    {
        "id": "signal_specificity",
        "name": "信号精确性",
        "weight": 20,
        "desc": "买卖条件必须有具体阈值，不能是模糊描述",
    },
    {
        "id": "risk_concrete",
        "name": "风控具体性",
        "weight": 15,
        "desc": "止损/止盈/仓位管理必须有具体数值",
    },
    {
        "id": "indicator_formula",
        "name": "指标公式",
        "weight": 15,
        "desc": "每个指标必须有数学公式",
    },
    {
        "id": "prohibitions",
        "name": "禁止事项",
        "weight": 10,
        "desc": "必须包含禁止事项 section",
    },
]


# ── 检查函数 ──────────────────────────────────────


def check_completeness(content: str) -> tuple[bool, str]:
    """检查所有核心 section 是否存在"""
    required_sections = [
        "策略元信息",
        "指标定义",
        "信号逻辑",
        "仓位管理",
        "风控规则",
        "回测参数",
        "禁止事项",
        "已知局限",
    ]
    missing = [s for s in required_sections if s not in content]

    # 按品种类型检查模板专属 section
    template_sections = {
        "期货": ["合约与展期规则", "期限结构"],
        "期权": ["波动率分析", "Greeks"],
        "组合策略": ["腿结构定义", "腿间相关性"],
    }
    detected_type = None
    for type_name, keywords in template_sections.items():
        for kw in keywords:
            if kw in content:
                detected_type = type_name
                break
        if detected_type:
            break

    if detected_type:
        for section in template_sections[detected_type]:
            if section not in content:
                missing.append(f"{section}（{detected_type}模板必需）")

    if missing:
        return False, f"缺少 section: {', '.join(missing)}"
    return True, "全部 section 存在"


def check_no_placeholder(content: str) -> tuple[bool, str]:
    """检查是否有残留的占位符"""
    placeholders = [
        (r"\[需用户确认\]", "[需用户确认]"),
        (r"\[需用户确认[^\]]*\]", "[需用户确认...]"),
        (r"\[X\]", "[X]"),
        (r"\[N\]", "[N]"),
        (r"\[A, B\]", "[A, B]"),
        (r"\[名称\]", "[名称]"),
        (r"\[具体[^\]]*\]", "[具体...]"),
    ]
    found = []
    for pattern, label in placeholders:
        matches = re.findall(pattern, content)
        if matches:
            found.append(f"{label} ×{len(matches)}")
    if found:
        return False, f"残留占位符: {', '.join(found)}"
    return True, "无残留占位符"


def _extract_section(content: str, markers: list[str]) -> str:
    """从 markdown 内容中提取指定 section（到下一个 ## 标题为止）"""
    for marker in markers:
        idx = content.find(marker)
        if idx != -1:
            end = len(content)
            for m in re.finditer(r"\n## [^#]", content[idx + 4:]):
                end = idx + 4 + m.start()
                break
            return content[idx:end]
    return ""


def check_signal_specificity(content: str) -> tuple[bool, str]:
    """检查买卖信号是否有具体阈值"""
    signal_section = _extract_section(content, [
        "信号逻辑", "开仓信号", "平仓信号", "买入信号", "卖出信号",
        "开多信号", "平多信号", "开空信号", "平空信号",
    ])

    if not signal_section:
        return False, "未找到信号逻辑 section"

    # 检查是否有具体数值（百分比、数字阈值）
    has_number = bool(re.search(r"\d+\.?\d*\s*[%]?", signal_section))
    has_operator = bool(re.search(r"[><=]", signal_section))
    has_indicator = bool(re.search(r"(RSI|MA|MACD|ATR|EMA|SMA|BOLL|KDJ|BBANDS|VWAP)", signal_section, re.IGNORECASE))

    issues = []
    if not has_indicator:
        issues.append("未检测到具体技术指标名称")
    if not has_operator:
        issues.append("未检测到比较运算符 (>, <, =)")
    if not has_number:
        issues.append("未检测到具体数值阈值")

    if issues:
        return False, "; ".join(issues)
    return True, "信号条件包含具体指标和阈值"


def check_risk_concrete(content: str) -> tuple[bool, str]:
    """检查风控规则是否有具体数值"""
    risk_section = ""
    for marker in ["风控规则", "Greeks 风控", "通用风控", "组合级风控"]:
        idx = content.find(marker)
        if idx != -1:
            risk_section = content[idx:idx + 2000]
            break

    if not risk_section:
        return False, "未找到风控规则 section"

    # 检查是否有止损/止盈相关数值
    has_stop_loss = bool(re.search(r"(止损|最大亏损|stop.?loss)", risk_section, re.IGNORECASE))
    has_value = bool(re.search(r"\d+\.?\d*\s*%", risk_section))

    issues = []
    if not has_stop_loss:
        issues.append("未检测到止损规则")
    if not has_value:
        issues.append("未检测到具体百分比/数值")

    if issues:
        return False, "; ".join(issues)
    return True, "风控规则包含具体数值"


def check_indicator_formula(content: str) -> tuple[bool, str]:
    """检查指标是否有数学公式"""
    indicator_section = ""
    idx = content.find("指标定义")
    if idx != -1:
        # 取到下一个顶级 section（## 但不是 ###）之前
        end = idx + 3000
        for m in re.finditer(r"\n## [^#]", content[idx + 4:]):
            end = idx + 4 + m.start()
            break
        indicator_section = content[idx:end]

    if not indicator_section:
        return False, "未找到指标定义 section"

    # 检查公式特征
    has_formula = bool(re.search(r"[=+\-*/∑Σsqrt]", indicator_section))
    has_function = bool(re.search(r"(SMA|EMA|RSI|MACD|ATR|STD|MEAN|SUM|MAX|MIN|LOG|abs|sqrt)\s*\(", indicator_section, re.IGNORECASE))

    if not has_formula and not has_function:
        return False, "未检测到数学公式"
    return True, "指标包含数学公式"


def check_prohibitions(content: str) -> tuple[bool, str]:
    """检查禁止事项 section 是否存在且有实质内容"""
    idx = content.find("禁止事项")
    if idx == -1:
        return False, "缺少禁止事项 section"

    prohibition_section = content[idx:idx + 1500]
    # 检查是否有禁止条目（❌ 或编号列表）
    has_items = bool(re.search(r"(❌|\d+\.)", prohibition_section))
    if not has_items:
        return False, "禁止事项 section 为空"
    return True, "禁止事项 section 存在且有条目"


# ── 主流程 ──────────────────────────────────────


def run_check(filepath: str) -> dict:
    """执行所有检查，返回结果"""
    path = Path(filepath)
    if not path.exists():
        return {"error": f"文件不存在: {filepath}", "score": 0, "passed": False}

    content = path.read_text(encoding="utf-8")

    # 跳过模板文件（未填充的模板）
    if "本文档是策略的精确设计规格" in content and "[策略名称]" in content:
        return {"error": "这是模板文件，不是已填充的策略文档", "score": 0, "passed": False}

    check_funcs = {
        "completeness": check_completeness,
        "no_placeholder": check_no_placeholder,
        "signal_specificity": check_signal_specificity,
        "risk_concrete": check_risk_concrete,
        "indicator_formula": check_indicator_formula,
        "prohibitions": check_prohibitions,
    }

    results = []
    total_score = 0
    all_passed = True

    for check_def in CHECKS:
        func = check_funcs[check_def["id"]]
        passed, detail = func(content)
        weight = check_def["weight"]
        score = weight if passed else 0
        total_score += score
        if not passed:
            all_passed = False

        results.append({
            "id": check_def["id"],
            "name": check_def["name"],
            "weight": weight,
            "passed": passed,
            "detail": detail,
        })

    return {
        "file": str(path),
        "score": total_score,
        "max_score": 100,
        "passed": all_passed,
        "results": results,
    }


def print_report(result: dict):
    """打印检查报告"""
    if "error" in result:
        print(f"❌ {result['error']}")
        return

    print("=" * 50)
    print(f"  策略文档质量检查: {result['file']}")
    print("=" * 50)

    for r in result["results"]:
        status = "✓" if r["passed"] else "✗"
        weight_info = f"({r['weight']}分)"
        print(f"\n  {status} {r['name']} {weight_info}")
        print(f"    {r['detail']}")

    score = result["score"]
    passed = result["passed"]
    status = "✅ 通过" if passed else "❌ 未通过"
    print(f"\n{'─' * 50}")
    print(f"  总分: {score}/100  {status}")
    if not passed:
        print(f"  未通过的检查项需要修复后重新检查")
    print()


def main():
    if len(sys.argv) < 2:
        print("用法: python3 quality_check.py <STRATEGY_DESIGN.md路径>")
        sys.exit(2)

    filepath = sys.argv[1]
    result = run_check(filepath)
    print_report(result)

    # 输出 JSON 供 AI 解析（仅文件存在时）
    if result.get("error"):
        sys.exit(1)
    json_path = Path(filepath).parent / "quality_report.json"
    import json
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    sys.exit(0 if result.get("passed", False) else 1)


if __name__ == "__main__":
    main()
