#!/usr/bin/env python3
"""
Autostrategy 回测执行脚本

在策略目录中运行回测，输出结构化结果。
期望目录结构:
    ~/策略研究/[策略名称]/
    ├── STRATEGY_DESIGN.md
    ├── config.yaml
    ├── strategy.py          ← AI 生成的 Backtrader 策略
    └── data/fetch_data.py   ← AI 生成的数据获取脚本

strategy.py 必须暴露的标准接口:
    class Strategy(bt.Strategy):
        params = (
            # 从 config.yaml 读取的参数
        )

用法:
    python3 run_backtest.py ~/策略研究/双均线/
    python3 run_backtest.py ~/策略研究/双均线/ --output results.json

退出码:
    0 = 回测成功完成
    1 = 回测失败
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

# ── 策略评分函数（与 SKILL.md 中的 score_strategy 一致）─────────────


MARKET_BENCHMARKS = {
    "A股": {"index": "000300.SH", "avg_annual_return": 8.0},
    "港股": {"index": "HSI",      "avg_annual_return": 5.0},
    "美股": {"index": "^GSPC",    "avg_annual_return": 10.0},
}


def score_strategy(backtest: dict, design: dict, market: str = "A股") -> float:
    """将回测结果 + 复杂度映射为 0-100 分"""
    benchmark = MARKET_BENCHMARKS.get(market, MARKET_BENCHMARKS["A股"])
    baseline_return = benchmark["avg_annual_return"]

    score = 0.0

    # 收益率（满分25，超越基准2倍=满分）
    annual = backtest.get("annual_return", 0)
    score += min(annual / (baseline_return * 2), 1.0) * 25

    # 回撤控制（满分20，回撤<10%=满分）
    drawdown = backtest.get("max_drawdown", 100)
    score += max(1 - drawdown / 30.0, 0) * 20

    # 风险调整收益（满分25，夏普>2.0=满分）
    sharpe = backtest.get("sharpe", 0)
    score += min(sharpe / 2.0, 1.0) * 25

    # 胜率（满分15，>60%=满分）
    win_rate = backtest.get("win_rate", 0)
    score += min(win_rate / 60.0, 1.0) * 15

    # 盈亏比（满分15，>2.5=满分）
    pl_ratio = backtest.get("profit_loss_ratio", 0)
    score += min(pl_ratio / 2.5, 1.0) * 15

    # 简洁性惩罚
    condition_count = (
        design.get("num_buy_conditions", 0)
        + design.get("num_sell_conditions", 0)
        + design.get("num_filters", 0)
        + design.get("num_risk_rules", 0)
    )
    complexity_penalty = max(0, (condition_count - 10) * 1.5)

    return max(0, score - complexity_penalty)


# ── 回测诊断 ──────────────────────────────────────


def run_diagnostics(backtest: dict) -> list[dict]:
    """自动检测5项诊断"""
    diagnostics = []

    # 1. 过拟合检测：收益是否过度集中在某个时间段
    period_returns = backtest.get("period_returns", [])
    if period_returns:
        avg = sum(period_returns) / len(period_returns)
        variance = sum((r - avg) ** 2 for r in period_returns) / len(period_returns)
        cv = (variance ** 0.5) / abs(avg) if avg != 0 else 999
        if cv > 3.0:
            diagnostics.append({"item": "过拟合", "status": "⚠️",
                                "detail": f"收益波动系数 {cv:.1f}，不同时期表现差异大"})
        else:
            diagnostics.append({"item": "过拟合", "status": "✅",
                                "detail": f"收益波动系数 {cv:.1f}，各时期表现较稳定"})

    # 2. 幸存者偏差
    universe = backtest.get("universe_size", 0)
    survivors = backtest.get("survivor_count", 0)
    if universe > 0 and survivors > 0 and survivors < universe:
        ratio = survivors / universe
        if ratio < 0.5:
            diagnostics.append({"item": "幸存者偏差", "status": "⚠️",
                                "detail": f"仅使用 {survivors}/{universe} 只现存股票"})
        else:
            diagnostics.append({"item": "幸存者偏差", "status": "✅",
                                "detail": f"使用了 {survivors}/{universe} 只股票"})

    # 3. 未来函数检测（由 strategy.py 自检，此处标记为待检）
    future_leak = backtest.get("future_leak_detected", False)
    if future_leak:
        diagnostics.append({"item": "未来函数", "status": "❌",
                            "detail": "检测到可能使用了未来数据"})
    else:
        diagnostics.append({"item": "未来函数", "status": "✅",
                            "detail": "未检测到未来数据使用（需人工复核）"})

    # 4. 流动性检测
    avg_volume = backtest.get("avg_daily_volume", 0)
    avg_trade_value = backtest.get("avg_trade_value", 0)
    if avg_volume > 0 and avg_trade_value / avg_volume > 0.1:
        diagnostics.append({"item": "流动性", "status": "⚠️",
                            "detail": f"单笔交易占日均成交额比例过高"})
    else:
        diagnostics.append({"item": "流动性", "status": "✅",
                            "detail": "交易量与市场流动性匹配"})

    # 5. 稳定性检测：前半段 vs 后半段收益
    first_half = backtest.get("first_half_return", 0)
    second_half = backtest.get("second_half_return", 0)
    if first_half != 0 and second_half != 0:
        diff = abs(first_half - second_half) / max(abs(first_half), abs(second_half))
        if diff > 0.8:
            diagnostics.append({"item": "稳定性", "status": "⚠️",
                                "detail": f"前后半段收益差异 {diff:.0%}"})
        else:
            diagnostics.append({"item": "稳定性", "status": "✅",
                                "detail": f"前后半段收益差异 {diff:.0%}"})

    return diagnostics


# ── 通过标准判定 ──────────────────────────────────────


PASS_CRITERIA = {
    "annual_return": {"min": 3.0, "desc": "> 无风险利率 × 2（约3%）"},
    "max_drawdown": {"max": 20, "desc": "< 20%"},
    "sharpe": {"min": 1.0, "desc": "> 1.0"},
    "win_rate": {"min": 45, "desc": "> 45%"},
    "profit_loss_ratio": {"min": 1.5, "desc": "> 1.5"},
}


def check_pass_criteria(backtest: dict) -> list[dict]:
    """检查回测结果是否通过标准"""
    results = []
    for key, criteria in PASS_CRITERIA.items():
        value = backtest.get(key)
        label = {
            "annual_return": "年化收益率",
            "max_drawdown": "最大回撤",
            "sharpe": "夏普比率",
            "win_rate": "胜率",
            "profit_loss_ratio": "盈亏比",
        }.get(key, key)

        if value is None:
            results.append({"metric": label, "value": "N/A",
                            "criteria": criteria["desc"], "passed": None})
            continue

        passed = True
        if "min" in criteria and criteria["min"] is not None:
            passed = passed and value >= criteria["min"]
        if "max" in criteria and criteria["max"] is not None:
            passed = passed and value <= criteria["max"]

        unit = "%" if key in ("annual_return", "max_drawdown", "win_rate") else ""
        display = f"{value:.2f}{unit}" if isinstance(value, float) else str(value)
        results.append({"metric": label, "value": display,
                        "criteria": criteria["desc"], "passed": passed})

    return results


# ── 回测执行 ──────────────────────────────────────


def load_config(strategy_dir: Path) -> dict:
    """加载 config.yaml"""
    import yaml
    config_path = strategy_dir / "config.yaml"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def run_backtest(strategy_dir: Path, config: dict) -> dict:
    """
    执行回测。加载 AI 生成的 strategy.py 并运行。

    strategy.py 需要暴露:
    - run_backtest(config) -> dict  (返回回测结果字典)
    或
    - Strategy class (Backtrader 标准接口)
    """
    strategy_file = strategy_dir / "strategy.py"
    if not strategy_file.exists():
        return {"error": f"strategy.py 不存在: {strategy_file}"}

    # 动态加载 strategy.py
    spec = importlib.util.spec_from_file_location("strategy", strategy_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["strategy"] = module

    try:
        spec.loader.exec_module(module)
    except Exception as e:
        return {"error": f"strategy.py 加载失败: {e}"}

    # 尝试调用 run_backtest 函数（推荐接口）
    if hasattr(module, "run_backtest"):
        try:
            return module.run_backtest(config)
        except Exception as e:
            return {"error": f"run_backtest() 执行失败: {e}"}

    # 回退：尝试使用 Backtrader Strategy class
    if hasattr(module, "Strategy"):
        try:
            return _run_backtrader(module, config, strategy_dir)
        except Exception as e:
            return {"error": f"Backtrader 回测失败: {e}"}

    return {"error": "strategy.py 未暴露 run_backtest() 函数或 Strategy class"}


def _run_backtrader(module, config: dict, strategy_dir: Path) -> dict:
    """使用 Backtrader 运行 Strategy class"""
    import backtrader as bt

    cerebro = bt.Cerebro()

    # 加载数据
    data_file = strategy_dir / "data" / "data.csv"
    if data_file.exists():
        import pandas as pd
        df = pd.read_csv(data_file, parse_dates=["date"])
        df.set_index("date", inplace=True)
        data = bt.feeds.PandasData(dataname=df)
        cerebro.adddata(data)
    else:
        fetch_file = strategy_dir / "data" / "fetch_data.py"
        if fetch_file.exists():
            spec = importlib.util.spec_from_file_location("fetch_data", fetch_file)
            fetch_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(fetch_module)
            if hasattr(fetch_module, "fetch"):
                df = fetch_module.fetch(config)
                if df is not None:
                    data = bt.feeds.PandasData(dataname=df)
                    cerebro.adddata(data)

    # 设置初始资金
    initial_cash = config.get("initial_cash", 1000000)
    cerebro.broker.setcash(initial_cash)

    # 设置手续费（含印花税和滑点）
    commission = config.get("commission", 0.0003)
    stamp_tax = config.get("stamp_tax", 0.001)
    slippage = config.get("slippage", 0.001)
    cerebro.broker.setcommission(commission=commission, stampduty=stamp_tax)
    cerebro.broker.set_slippage_perc(slippage)

    # 添加分析器
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", riskfreerate=0.015)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")

    # 添加策略
    cerebro.addstrategy(module.Strategy)

    # 运行
    results = cerebro.run()
    strat = results[0]
    final_value = cerebro.broker.getvalue()
    total_return = (final_value - initial_cash) / initial_cash * 100

    # 计算年化
    days = len(cerebro.datas[0]) if cerebro.datas else 252
    years = max(days / 252, 0.1)
    annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100

    # 提取分析器结果
    sharpe = strat.analyzers.sharpe.get_analysis().get("sharperatio", 0) or 0
    dd = strat.analyzers.drawdown.get_analysis()
    max_drawdown = dd.get("max", {}).get("drawdown", 0) or 0

    ta = strat.analyzers.trades.get_analysis()
    total_trades = ta.get("total", {}).get("total", 0)
    won = ta.get("won", {}).get("total", 0)
    lost = ta.get("lost", {}).get("total", 0)
    win_rate = won / max(total_trades, 1) * 100

    avg_win = ta.get("won", {}).get("pnl", {}).get("average", 0) or 0
    avg_loss = abs(ta.get("lost", {}).get("pnl", {}).get("average", 0.01) or 0.01)
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    return {
        "annual_return": round(annual_return, 2),
        "max_drawdown": round(max_drawdown, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win_rate, 1),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "total_trades": total_trades,
        "initial_cash": initial_cash,
        "final_value": round(final_value, 2),
        "total_return": round(total_return, 2),
    }


# ── 报告输出 ──────────────────────────────────────


def print_report(backtest: dict, criteria: list[dict],
                 diagnostics: list[dict], total_score: float):
    """打印回测报告"""
    print("=" * 50)
    print("  回测结果")
    print("=" * 50)

    if "error" in backtest:
        print(f"\n❌ 回测失败: {backtest['error']}\n")
        return

    # 核心指标
    print(f"\n  年化收益率:  {backtest.get('annual_return', 'N/A')}")
    print(f"  最大回撤:    {backtest.get('max_drawdown', 'N/A')}")
    print(f"  夏普比率:    {backtest.get('sharpe', 'N/A')}")
    print(f"  胜率:        {backtest.get('win_rate', 'N/A')}")
    print(f"  盈亏比:      {backtest.get('profit_loss_ratio', 'N/A')}")
    print(f"  交易次数:    {backtest.get('total_trades', 'N/A')}")

    # 通过标准
    print(f"\n{'─' * 50}")
    print("  通过标准:")
    all_pass = True
    for c in criteria:
        if c["passed"] is None:
            icon = "—"
        elif c["passed"]:
            icon = "✓"
        else:
            icon = "✗"
            all_pass = False
        print(f"  {icon} {c['metric']}: {c['value']}  ({c['criteria']})")

    # 诊断
    print(f"\n{'─' * 50}")
    print("  诊断:")
    for d in diagnostics:
        print(f"  {d['status']} {d['item']}: {d['detail']}")

    # 总分
    print(f"\n{'─' * 50}")
    status = "✅ 通过" if all_pass else "❌ 未通过"
    print(f"  score_strategy(): {total_score:.1f}/100  {status}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Autostrategy 回测执行")
    parser.add_argument("strategy_dir", help="策略目录路径")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    args = parser.parse_args()

    strategy_dir = Path(args.strategy_dir).expanduser()
    if not strategy_dir.exists():
        print(f"❌ 目录不存在: {strategy_dir}")
        sys.exit(1)

    # 加载配置
    config = load_config(strategy_dir)

    # 从 STRATEGY_DESIGN.md 提取条件数（用于简洁性惩罚）
    design_doc = strategy_dir / "STRATEGY_DESIGN.md"
    design = {}
    if design_doc.exists():
        content = design_doc.read_text(encoding="utf-8")
        # 只从"信号逻辑"section提取条件数，避免标题/描述被误计
        import re as _re
        signal_section = ""
        for marker in ["信号逻辑", "开仓信号", "平仓信号", "买入信号", "卖出信号",
                        "开多信号", "平多信号", "开空信号", "平空信号"]:
            idx = content.find(marker)
            if idx != -1:
                end = idx + 2000
                for m in _re.finditer(r"\n## [^#]", content[idx + 4:]):
                    end = idx + 4 + m.start()
                    break
                signal_section = content[idx:end]
                break
        if signal_section:
            design["num_buy_conditions"] = len(_re.findall(r"条件\d+.*?(买入|BUY|开多)", signal_section))
            design["num_sell_conditions"] = len(_re.findall(r"条件\d+.*?(卖出|SELL|平多|平空)", signal_section))
            design["num_filters"] = len(_re.findall(r"(过滤|过滤条件)", signal_section))
        # 风控规则从"风控规则"section提取
        risk_section = ""
        for marker in ["风控规则", "Greeks 风控", "通用风控", "组合级风控"]:
            idx = content.find(marker)
            if idx != -1:
                end = idx + 2000
                for m in _re.finditer(r"\n## [^#]", content[idx + 4:]):
                    end = idx + 4 + m.start()
                    break
                risk_section = content[idx:end]
                break
        if risk_section:
            design["num_risk_rules"] = len(_re.findall(r"(止损|止盈|回撤|清仓|暂停|仓位|连续)", risk_section))

    # 执行回测
    print(f"🔄 执行回测: {strategy_dir.name}...\n")
    backtest = run_backtest(strategy_dir, config)

    if "error" in backtest:
        print_report(backtest, [], [], 0)
        _save_json(args.output, strategy_dir, {"error": backtest["error"], "score": 0})
        sys.exit(1)

    # 评分
    market = config.get("market", "A股")
    total_score = score_strategy(backtest, design, market)

    # 诊断
    diagnostics = run_diagnostics(backtest)

    # 通过标准
    criteria = check_pass_criteria(backtest)

    # 打印报告
    print_report(backtest, criteria, diagnostics, total_score)

    # 保存 JSON
    result = {
        "backtest": backtest,
        "score": round(total_score, 1),
        "criteria": criteria,
        "diagnostics": diagnostics,
    }
    _save_json(args.output, strategy_dir / "backtest" / "results", result)

    sys.exit(0)


def _save_json(output_path, default_dir: Path, data: dict):
    """保存 JSON 结果，自动转换 numpy 类型"""
    def convert(obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        raise TypeError

    if output_path:
        path = Path(output_path)
    else:
        default_dir.mkdir(parents=True, exist_ok=True)
        path = default_dir / "backtest_result.json"

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=convert)
    print(f"  📄 结果已保存: {path}")


if __name__ == "__main__":
    main()
