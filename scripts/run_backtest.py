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
    python3 run_backtest.py ~/策略研究/双均线/ --split 0.7
    python3 run_backtest.py ~/策略研究/双均线/ --sensitivity
    python3 run_backtest.py ~/策略研究/双均线/ --plot

退出码:
    0 = 回测成功完成
    1 = 回测失败
"""

import argparse
import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np

# ── 策略评分函数（与 SKILL.md 中的 score_strategy 一致）─────────────


MARKET_BENCHMARKS = {
    "A股": {"index": "000300.SH", "avg_annual_return": 8.0},
    "港股": {"index": "HSI",      "avg_annual_return": 5.0},
    "美股": {"index": "^GSPC",    "avg_annual_return": 10.0},
}


def _resolve_baseline_return(market: str, config: dict = None) -> float:
    """解析基准收益率。支持"多市场"——按标的数量加权平均。"""
    if market in MARKET_BENCHMARKS:
        return MARKET_BENCHMARKS[market]["avg_annual_return"]
    # 多市场：按 symbols 中各标的的实际市场加权
    if config and "symbols" in config:
        market_counts = {}
        for sym in config["symbols"]:
            m = sym.get("market", "A股")
            market_counts[m] = market_counts.get(m, 0) + 1
        total = sum(market_counts.values())
        weighted = sum(
            MARKET_BENCHMARKS.get(m, MARKET_BENCHMARKS["A股"])["avg_annual_return"] * cnt
            for m, cnt in market_counts.items()
        ) / total
        return weighted
    return MARKET_BENCHMARKS["A股"]["avg_annual_return"]


def score_strategy(backtest: dict, design: dict, market: str = "A股",
                   config: dict = None) -> float:
    """将回测结果 + 复杂度映射为 0-100 分"""
    baseline_return = _resolve_baseline_return(market, config)

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


def _load_strategy_module(strategy_dir: Path):
    """动态加载 strategy.py，返回模块对象。"""
    strategy_file = strategy_dir / "strategy.py"
    if not strategy_file.exists():
        return None
    spec = importlib.util.spec_from_file_location("strategy", strategy_file)
    module = importlib.util.module_from_spec(spec)
    sys.modules["strategy"] = module
    try:
        spec.loader.exec_module(module)
        return module
    except Exception as e:
        print(f"❌ strategy.py 加载失败: {e}")
        return None


def _execute_strategy(module, config: dict, strategy_dir: Path) -> dict:
    """执行已加载的 strategy 模块，返回回测结果 dict。"""
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


def run_single_backtest(strategy_dir: Path, config: dict) -> dict:
    """
    执行回测。加载 AI 生成的 strategy.py 并运行。

    strategy.py 需要暴露:
    - run_backtest(config) -> dict  (返回回测结果字典)
    或
    - Strategy class (Backtrader 标准接口)
    """
    module = _load_strategy_module(strategy_dir)
    if module is None:
        return {"error": f"strategy.py 不存在: {strategy_dir / 'strategy.py'}"}
    return _execute_strategy(module, config, strategy_dir)


def run_train_test_split(strategy_dir: Path, config: dict, split_ratio: float = 0.7) -> dict:
    """
    Train/Test Split 回测：前 split_ratio 时间段为训练集，后段为测试集。
    返回包含 train_result、test_result、decay_rate 的字典。
    """
    # ── 提取时间范围 ──
    start_str = config.get("start_date", "2020-01-01")
    end_str = config.get("end_date", "2025-12-31")

    try:
        from datetime import datetime
        start_dt = datetime.strptime(str(start_str), "%Y-%m-%d")
        end_dt = datetime.strptime(str(end_str), "%Y-%m-%d")
    except (ValueError, TypeError):
        return {"error": f"config.yaml 日期格式无效: start={start_str}, end={end_str}"}

    total_days = (end_dt - start_dt).days
    if total_days <= 0:
        return {"error": "回测时间范围无效"}

    split_days = int(total_days * split_ratio)
    split_dt = start_dt + __import__("datetime").timedelta(days=split_days)

    # ── 训练集回测 ──
    train_config = _deep_copy_config(config)
    train_config["start_date"] = str(start_dt.date())
    train_config["end_date"] = str(split_dt.date())

    print(f"📊 训练集回测: {start_dt.date()} ~ {split_dt.date()} "
          f"({split_ratio:.0%})")
    train_result = run_single_backtest(strategy_dir, train_config)

    # ── 测试集回测 ──
    test_config = _deep_copy_config(config)
    test_config["start_date"] = str((split_dt + __import__("datetime").timedelta(days=1)).date())
    test_config["end_date"] = str(end_dt.date())

    print(f"📊 测试集回测: {test_config['start_date']} ~ {test_config['end_date']} "
          f"({1 - split_ratio:.0%})")
    test_result = run_single_backtest(strategy_dir, test_config)

    # ── 计算衰减率 ──
    if "error" in train_result or "error" in test_result:
        return {
            "train_result": train_result,
            "test_result": test_result,
            "error": "训练集或测试集回测失败",
        }

    train_return = train_result.get("annual_return", 0)
    test_return = test_result.get("annual_return", 0)

    if abs(train_return) < 0.01:
        decay_rate = 0.0
    else:
        decay_rate = test_return / train_return

    # 衰减率评级
    if decay_rate < 0.3:
        verdict = "❌ 严重过拟合"
    elif decay_rate < 0.6:
        verdict = "⚠️ 有过拟合风险"
    else:
        verdict = "✅ 样本外稳定"

    return {
        "train_result": train_result,
        "test_result": test_result,
        "split_ratio": split_ratio,
        "train_period": f"{start_dt.date()} ~ {split_dt.date()}",
        "test_period": f"{test_config['start_date']} ~ {end_dt.date()}",
        "train_annual_return": train_return,
        "test_annual_return": test_return,
        "decay_rate": round(decay_rate, 4),
        "verdict": verdict,
    }


# ── 敏感度分析 ──────────────────────────────────────


def run_sensitivity_analysis(strategy_dir: Path, config: dict) -> dict:
    """
    对策略参数进行简单敏感度分析。
    逐个参数 ±10%/±20%，观察分数变化。
    """
    base_result = run_single_backtest(strategy_dir, config)
    if "error" in base_result:
        return base_result

    design = _extract_design_complexity(strategy_dir)
    market = config.get("market", "A股")
    base_score = score_strategy(base_result, design, market, config)

    indicators = config.get("indicators", {})
    sensitivity = []

    for param_name, param_value in indicators.items():
        if not isinstance(param_value, (int, float)):
            continue

        for delta_label, delta_factor in [("-20%", 0.8), ("-10%", 0.9), ("+10%", 1.1), ("+20%", 1.2)]:
            test_config = _deep_copy_config(config)
            test_config["indicators"][param_name] = round(param_value * delta_factor, 6)

            test_result = run_single_backtest(strategy_dir, test_config)
            if "error" in test_result:
                sensitivity.append({
                    "param": param_name, "delta": delta_label,
                    "error": test_result["error"],
                })
                continue

            test_score = score_strategy(test_result, design, market, test_config)
            score_diff = round(test_score - base_score, 2)

            sensitivity.append({
                "param": param_name,
                "delta": delta_label,
                "value": test_config["indicators"][param_name],
                "annual_return": test_result.get("annual_return"),
                "max_drawdown": test_result.get("max_drawdown"),
                "score": round(test_score, 2),
                "score_diff": score_diff,
            })

    # 按分数变化绝对值排序
    sensitivity.sort(key=lambda x: abs(x.get("score_diff", 0)), reverse=True)

    return {
        "base_score": round(base_score, 2),
        "sensitivity": sensitivity,
        "most_sensitive": sensitivity[0]["param"] if sensitivity else None,
    }


# ── 可视化 ──────────────────────────────────────


def _compute_buy_hold(config: dict) -> list:
    """计算买入持有基准净值曲线（简化版，基于 config 的日期范围）。"""
    # 买入持有需要真实价格数据，此处返回空列表表示不可用
    # strategy.py 的 daily_values 已经包含了净值曲线
    return []


def plot_backtest(backtest_result: dict, strategy_dir: Path):
    """
    生成回测净值曲线图。需要 backtest_result 中包含 daily_values 字段。
    """
    daily_values = backtest_result.get("daily_values", [])
    if not daily_values:
        print("⚠️ daily_values 字段缺失，无法生成图表。"
              "请在 strategy.py 的返回值中添加 daily_values 和 initial_cash。")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from datetime import datetime
    except ImportError:
        print("⚠️ matplotlib 未安装，无法生成图表。请运行: pip install matplotlib")
        return

    dates = [datetime.strptime(d["date"], "%Y-%m-%d") for d in daily_values]
    values = [d["value"] for d in daily_values]
    initial_cash = backtest_result.get("initial_cash", values[0] if values else 1)

    # 归一化为净值
    nav = [v / initial_cash for v in values]

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(dates, nav, label="策略净值", linewidth=1.5, color="#2563eb")
    ax.axhline(y=1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    # 标注回撤最大点
    peak = nav[0]
    max_dd_pos = 0
    max_dd_val = 0
    for i, n in enumerate(nav):
        if n > peak:
            peak = n
        dd = (peak - n) / peak
        if dd > max_dd_val:
            max_dd_val = dd
            max_dd_pos = i

    if max_dd_pos > 0:
        ax.annotate(f"最大回撤 {max_dd_val:.1%}",
                    xy=(dates[max_dd_pos], nav[max_dd_pos]),
                    xytext=(30, 30), textcoords="offset points",
                    arrowprops=dict(arrowstyle="->", color="red"),
                    fontsize=9, color="red")

    ax.set_title(f"策略净值曲线 — {strategy_dir.name}", fontsize=14)
    ax.set_ylabel("净值")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    plt.tight_layout()

    output_dir = strategy_dir / "backtest" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "backtest_plot.png"
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  📊 图表已保存: {output_path}")


# ── 辅助函数 ──────────────────────────────────────


def _deep_copy_config(config: dict) -> dict:
    """深拷贝 config，避免修改原始配置。"""
    return copy.deepcopy(config)


def _extract_section_content(text: str, markers: list[str], max_len: int = 2000) -> str:
    """从 Markdown 文本中提取指定 section 的内容。"""
    for marker in markers:
        idx = text.find(marker)
        if idx != -1:
            end = idx + max_len
            for m in re.finditer(r"\n## [^#]", text[idx + 4:]):
                end = idx + 4 + m.start()
                break
            return text[idx:end]
    return ""


def _count_conditions_in_subsection(section: str, patterns: list[str]) -> int:
    """在 section 文本中按多个 pattern 计数。"""
    count = 0
    for pattern in patterns:
        count += len(re.findall(pattern, section))
    return count


def _extract_design_complexity(strategy_dir: Path) -> dict:
    """从 STRATEGY_DESIGN.md 提取条件数（用于简洁性惩罚）"""
    design_doc = strategy_dir / "STRATEGY_DESIGN.md"
    design = {}
    if not design_doc.exists():
        return design

    content = design_doc.read_text(encoding="utf-8")

    # 从"信号逻辑"section提取条件数，避免标题/描述被误计
    signal_section = _extract_section_content(
        content,
        ["信号逻辑", "开仓信号", "平仓信号", "买入信号", "卖出信号",
         "开多信号", "平多信号", "开空信号", "平空信号"],
    )
    if signal_section:
        design["num_buy_conditions"] = _count_conditions_in_subsection(
            signal_section, [r"条件\d+.*?(买入|BUY|开多)"]
        )
        design["num_sell_conditions"] = _count_conditions_in_subsection(
            signal_section, [r"条件\d+.*?(卖出|SELL|平多|平空)"]
        )
        design["num_filters"] = _count_conditions_in_subsection(
            signal_section, [r"(过滤|过滤条件)"]
        )

    # 风控规则从"风控规则"section提取
    risk_section = _extract_section_content(
        content,
        ["风控规则", "Greeks 风控", "通用风控", "组合级风控"],
    )
    if risk_section:
        design["num_risk_rules"] = _count_conditions_in_subsection(
            risk_section, [r"(止损|止盈|回撤|清仓|暂停|仓位|连续)"]
        )

    return design


# ── Backtrader 回测引擎 ──────────────────────────────────────


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


def print_split_report(split_result: dict):
    """打印 Train/Test Split 报告"""
    print("=" * 50)
    print("  Train/Test Split 回测报告")
    print("=" * 50)

    if "error" in split_result and "train_result" not in split_result:
        print(f"\n❌ Split 回测失败: {split_result['error']}\n")
        return

    train = split_result.get("train_result", {})
    test = split_result.get("test_result", {})

    print(f"\n  训练集 ({split_result.get('train_period', 'N/A')}):")
    print(f"    年化收益率:  {train.get('annual_return', 'N/A')}")
    print(f"    最大回撤:    {train.get('max_drawdown', 'N/A')}")
    print(f"    夏普比率:    {train.get('sharpe', 'N/A')}")

    print(f"\n  测试集 ({split_result.get('test_period', 'N/A')}):")
    print(f"    年化收益率:  {test.get('annual_return', 'N/A')}")
    print(f"    最大回撤:    {test.get('max_drawdown', 'N/A')}")
    print(f"    夏普比率:    {test.get('sharpe', 'N/A')}")

    decay = split_result.get("decay_rate", 0)
    verdict = split_result.get("verdict", "N/A")
    print(f"\n{'─' * 50}")
    print(f"  衰减率: {decay:.2%}（测试集收益 / 训练集收益）")
    print(f"  判定:   {verdict}")
    print()


def print_sensitivity_report(sensitivity_result: dict):
    """打印敏感度分析报告"""
    print("=" * 50)
    print("  参数敏感度分析报告")
    print("=" * 50)

    if "error" in sensitivity_result:
        print(f"\n❌ 敏感度分析失败: {sensitivity_result['error']}\n")
        return

    base_score = sensitivity_result.get("base_score", 0)
    print(f"\n  基线分数: {base_score:.2f}")

    items = sensitivity_result.get("sensitivity", [])
    if not items:
        print("  无可分析参数")
        return

    print(f"\n{'─' * 50}")
    print(f"  {'参数':<20} {'变化':<6} {'分数':<8} {'差值':<8}")
    print(f"  {'─' * 42}")
    for item in items[:20]:  # 最多显示20条
        if "error" in item:
            print(f"  {item['param']:<20} {item['delta']:<6} ERROR")
        else:
            print(f"  {item['param']:<20} {item['delta']:<6} "
                  f"{item['score']:<8.2f} {item['score_diff']:+.2f}")

    most = sensitivity_result.get("most_sensitive")
    if most:
        print(f"\n  最敏感参数: {most}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Autostrategy 回测执行")
    parser.add_argument("strategy_dir", help="策略目录路径")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    parser.add_argument("--split", type=float, default=None,
                        help="Train/Test Split 比例（如 0.7 表示前 70%% 训练）")
    parser.add_argument("--sensitivity", action="store_true",
                        help="运行参数敏感度分析")
    parser.add_argument("--plot", action="store_true",
                        help="生成回测净值曲线图")
    args = parser.parse_args()

    strategy_dir = Path(args.strategy_dir).expanduser()
    if not strategy_dir.exists():
        print(f"❌ 目录不存在: {strategy_dir}")
        sys.exit(1)

    # 加载配置
    config = load_config(strategy_dir)

    # 从 STRATEGY_DESIGN.md 提取条件数（用于简洁性惩罚）
    design = _extract_design_complexity(strategy_dir)

    # ── Train/Test Split 模式 ──
    if args.split is not None:
        print(f"🔄 执行 Train/Test Split 回测: {strategy_dir.name} "
              f"(split={args.split})...\n")
        split_result = run_train_test_split(strategy_dir, config, args.split)
        print_split_report(split_result)

        output_dir = strategy_dir / "backtest" / "results"
        output_dir.mkdir(parents=True, exist_ok=True)
        _save_json(args.output, output_dir, {
            "mode": "train_test_split",
            "split_result": split_result,
        })
        sys.exit(0 if "error" not in split_result else 1)

    # ── 敏感度分析模式 ──
    if args.sensitivity:
        print(f"🔄 执行参数敏感度分析: {strategy_dir.name}...\n")
        sensitivity_result = run_sensitivity_analysis(strategy_dir, config)
        print_sensitivity_report(sensitivity_result)

        output_dir = strategy_dir / "backtest" / "results"
        output_dir.mkdir(parents=True, exist_ok=True)
        _save_json(args.output, output_dir, {
            "mode": "sensitivity",
            "sensitivity_result": sensitivity_result,
        })
        sys.exit(0 if "error" not in sensitivity_result else 1)

    # ── 标准回测模式 ──
    print(f"🔄 执行回测: {strategy_dir.name}...\n")
    backtest = run_single_backtest(strategy_dir, config)

    if "error" in backtest:
        print_report(backtest, [], [], 0)
        _save_json(args.output, strategy_dir / "backtest" / "results",
                   {"error": backtest["error"], "score": 0})
        sys.exit(1)

    # 评分
    market = config.get("market", "A股")
    total_score = score_strategy(backtest, design, market, config)

    # 诊断
    diagnostics = run_diagnostics(backtest)

    # 通过标准
    criteria = check_pass_criteria(backtest)

    # 打印报告
    print_report(backtest, criteria, diagnostics, total_score)

    # 可视化
    if args.plot:
        plot_backtest(backtest, strategy_dir)

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
