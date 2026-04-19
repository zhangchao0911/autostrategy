# Autostrategy

> AI 驱动的量化交易策略自动生成 Skill，专为 [Claude Code](https://claude.ai/code)、Gemini CLI、Copilot CLI 等 AI Agent 设计。

[![Skill](https://img.shields.io/badge/Skill-autostrategy-blue)](https://github.com/zhangchao0911/autostrategy)
[![Market](https://img.shields.io/badge/Market-A%E8%82%A1%20%7C%20%E6%B8%AF%E8%82%A1%20%7C%20%E7%BE%8E%E8%82%A1-green)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

---

> ⚠️ **免责声明**：本工具生成的策略仅供学习和研究用途，不构成任何投资建议。量化交易有风险，过往回测表现不代表未来收益。

## 合规说明

**本 Skill 的定位是学习工具，帮助用户理解量化策略的设计逻辑和验证方法。**

- **学习导向**：策略生成和回测的目的是帮助用户学习量化交易知识、理解策略原理，而非提供可直接用于实盘的交易系统
- **策略验证**：回测结果仅反映历史数据上的表现，不预示未来收益。实盘交易受滑点、流动性、市场冲击等影响，实际表现可能与回测有显著差异
- **实盘建议**：如用户计划将策略用于实盘交易，请务必充分了解相关风险，建议先进行长时间的模拟盘验证，并根据自身风险承受能力谨慎决策
- **投资责任**：所有投资决策由用户自行做出，本工具不对任何因使用本工具产生的投资损失承担责任
- **数据合规**：本工具使用的数据均来自公开市场数据源，用户应确保其数据获取和使用符合当地法律法规

## 它能做什么？

Autostrategy 是一个 AI Agent Skill，让量化策略开发变得像对话一样简单：

| 你说什么 | 它做什么 |
|---------|---------|
| "帮我设计一个双均线交叉策略" | 自动生成完整策略代码 + 回测验证 |
| "我想做一个A股量化策略，但不确定用什么方法" | 诊断推荐 → 选择方法 → 生成策略 |
| "根据某博主的投资观点做个策略" | 互联网研究 → 提炼交易逻辑 → 量化策略 |
| "这个策略回测一下" | 运行回测 → 输出评估报告 |
| "优化这个策略的回测结果" | 自动迭代优化 → 只保留有改进的版本 |

## 核心理念

### STRATEGY_DESIGN.md — 「系统施工图纸」

这是 Autostrategy 最核心的设计：**所有策略逻辑先落在设计文档上，代码只是文档的严格翻译产物。**

```
用户需求 → STRATEGY_DESIGN.md（精确规格）→ strategy.py（严格翻译）→ 回测验证
```

这意味着：
- AI 不会「自由发挥」，每行代码都有设计文档对应
- 策略逻辑可追溯、可审计、可复现
- 修改策略时改文档，代码跟随更新

## 四种入口路径

```
┌─────────────────────────────────────────────────────┐
│                   用户输入                            │
├─────────────┬───────────┬───────────┬───────────────┤
│  明确需求    │  模糊需求  │  已有策略  │  大V/博主     │
│  "双均线交叉"│ "想做个    │ "优化这个  │ "按某博主的   │
│             │  A股策略"  │  回测结果" │  投资逻辑"    │
├─────────────┼───────────┼───────────┼───────────────┤
│ 直接分析     │ 诊断推荐   │ 优化迭代   │ 互联网研究    │
│      ↓      │     ↓     │     ↓     │      ↓       │
│         STRATEGY_DESIGN.md                          │
│                    ↓                                │
│            strategy.py + 回测                       │
│                    ↓                                │
│             评估 → 优化 → 人类确认                    │
└─────────────────────────────────────────────────────┘
```

## 适用市场

| 市场 | 数据源 | 交易规则 |
|------|--------|---------|
| **A股** | [FTShare](https://github.com/zhangchao0911/all-in-one)（免费） | T+1，涨跌停 ±10%/±20% |
| **港股** | FutuAPI（需 Futu OpenD） | T+0，无涨跌停 |
| **美股** | FutuAPI（需 Futu OpenD） | T+0，PDT 规则 |

> 期货、期权暂不支持，后续版本逐步加入。

## 快速开始

### 安装

```bash
# 使用 skills CLI 安装
npx skills add zhangchao0911/autostrategy --yes
```

安装后，在 Claude Code / Gemini CLI / Copilot CLI 中直接使用，无需额外配置。

### 环境准备（可选）

如果需要运行回测，安装 Python 依赖：

```bash
pip install numpy pandas pyyaml
```

如果需要获取行情数据：

- **A股 ETF/股票**：安装 [ftshare-all-in-one](https://github.com/zhangchao0911/all-in-one) Skill（免费，推荐）
- **港美股**：安装 FutuAPI Skill（需 [Futu OpenD](https://www.futunn.com/download/openAPI) 运行）

### 使用示例

在 AI Agent 中直接说：

```
# 示例1：明确策略
"帮我设计一个动态网格策略，标的是腾讯控股和小鹏汽车"

# 示例2：模糊需求
"我想做一个港股量化策略，但不清楚用什么方法"

# 示例3：博主策略
"帮我根据某大V在微博上的投资观点做个量化策略"

# 示例4：优化已有策略
"优化这个策略的回测结果，降低最大回撤"
```

## 项目结构

```
autostrategy/
├── SKILL.md                          # Skill 定义（AI Agent 读取）
├── scripts/
│   ├── env_setup.py                  # 环境检查与依赖安装
│   ├── quality_check.py              # 策略代码质量检查
│   └── run_backtest.py               # 回测执行与评估
├── examples/
│   └── dynamic-grid-multi-market/    # 示例：动态网格多标的策略
│       ├── STRATEGY_DESIGN.md        # 策略设计文档（施工图纸）
│       ├── config.yaml               # 回测参数配置
│       ├── strategy.py               # 策略实现代码
│       ├── requirements.txt          # Python 依赖
│       └── data/
│           └── fetch_data.py         # 数据获取脚本
└── skills-lock.json
```

## 示例策略：动态网格多标的

内置了一个完整的动态网格策略示例，覆盖 5 个跨市场标的：

| 标的 | 市场 | 数据源 |
|------|------|--------|
| 腾讯控股 (0700.HK) | 港股 | FutuAPI |
| 科创50ETF (588000.SH) | A股 | FTShare |
| 中证2000ETF (563300.SH) | A股 | FTShare |
| 小鹏汽车 (9868.HK) | 港股 | FutuAPI |
| 特斯拉 (TSLA) | 美股 | FutuAPI |

真实数据回测结果（2024-2025）：

| 指标 | 数值 |
|------|------|
| 年化收益率 | 11.99% |
| 最大回撤 | 30.47% |
| 夏普比率 | 0.49 |
| 胜率 | 75.2% |
| 总交易次数 | 276 |
| 期末资产 | ¥1,330,743 |

## 策略评估体系

Autostrategy 使用 `score_strategy()` 对策略进行量化评分，从 5 个维度评估 + 简洁性惩罚：

| 维度 | 满分 | 满分条件 |
|------|------|---------|
| 年化收益率 | 25 | > 基准指数年均收益 × 2（沪深300 8% / 恒生 5% / 标普 10%）|
| 最大回撤 | 20 | < 10%（回撤≥30%得0分）|
| 夏普比率 | 25 | > 2.0 |
| 胜率 | 15 | > 60% |
| 盈亏比 | 15 | > 2.5 |
| 简洁性惩罚 | — | 条件数 > 10 时，每个额外条件扣 1.5 分 |

同时检测：过拟合、幸存者偏差、未来函数、流动性匹配、前后半段收益稳定性。

## 设计原则

| # | 原则 | 说明 |
|---|------|------|
| 1 | 简洁性优先 | 分数提升必须大于复杂度增加 |
| 2 | 文档是核心 | 所有逻辑先写入 STRATEGY_DESIGN.md |
| 3 | 入口分流 | 不假设用户知道怎么用，提供明确路径引导 |
| 4 | 人在回路 | 策略方向和回测结果必须人类确认 |
| 5 | 量化评估 | 用 score_strategy() 一个数字决定 keep 或 revert |
| 6 | 免费优先 | 只推荐免费数据源，不引导用户付费 |
| 7 | 不推实盘 | 定位是策略创建和验证，不推荐实盘交易 |

## 技术栈

- **语言**：Python 3.9+
- **数据处理**：NumPy, Pandas
- **数据源**：[FTShare](https://github.com/zhangchao0911/all-in-one)（A股）、FutuAPI（港美股）
- **AI Agent 兼容**：Claude Code, Gemini CLI, Copilot CLI, Codex, Cline 等

## 相关项目

- [all-in-one](https://github.com/zhangchao0911/all-in-one) — 免费的 A 股/港股行情数据 Skill
- [darwin-skill](https://github.com/alchaincyf/darwin-skill) — AI Skill 持续优化框架

## Author

**Maxzhang**

- 小红书：[https://xhslink.com/m/8MXvZUynFYx](https://xhslink.com/m/8MXvZUynFYx)
- Email：maxzhang0911@gmail.com
- GitHub：[@zhangchao0911](https://github.com/zhangchao0911)

## License

MIT License
