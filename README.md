# Autostrategy

> AI 驱动的量化策略自动生成工具。输入策略需求 → Agent 设计 → 代码生成 → 回测验证 → 自主优化。

[![Skill](https://img.shields.io/badge/Skill-autostrategy-blue)](https://github.com/rivar0107/autostrategy)
[![Market](https://img.shields.io/badge/Market-A%E8%82%A1%20%7C%20%E6%B8%AF%E8%82%A1%20%7C%20%E7%BE%8E%E8%82%A1-green)]()
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> ⚠️ **免责声明**：本工具生成的策略仅供学习和研究用途，不构成任何投资建议。量化交易有风险，过往回测表现不代表未来收益。

## 它能做什么？

| 入口 | 你说 | 它做 |
|------|------|------|
| **明确需求** | "帮我设计一个双均线交叉策略" | 直接分析 → 设计文档 → 代码 + 回测 |
| **模糊需求** | "我想做A股量化，但不确定用什么方法" | 诊断推荐 → 选方向 → 生成策略 |
| **博主策略** | "按某大V的投资逻辑做个策略" | 互联网研究 → 提炼逻辑 → 量化策略 |
| **优化迭代** | "优化这个策略的回测结果" | 诊断弱点 → 5轮自主优化 → 输出报告 |

## 核心设计

### 文档驱动

**STRATEGY_DESIGN.md 是「系统施工图纸」** — 所有策略逻辑先落在设计文档上，代码只是文档的严格翻译产物。

```
用户需求 → STRATEGY_DESIGN.md（精确规格）→ strategy.py（严格翻译）→ 回测验证
```

这意味着：AI 不会「自由发挥」，每行代码都有文档对应；修改策略时改文档，代码跟随更新。

### Agent 化工作流

Autostrategy 采用**多 Agent 串联**架构，用户只需在 3 个关键审批点参与决策：

```
用户输入
    ↓
┌─────────────────┐  Phase 1: 策略设计 Agent
│  设计 Agent      │  → 产出 STRATEGY_DESIGN.md
│  (design_agent)  │
└────────┬────────┘
         ↓ ⏸ 审批点 1：确认设计文档
┌─────────────────┐  Phase 2: 代码生成 Agent
│  代码 Agent      │  → 产出 strategy.py + 回测报告
│  (codegen_agent) │
└────────┬────────┘
         ↓ ⏸ 审批点 2：确认回测结果
┌─────────────────┐  Phase 3: 优化 Agent（自主/交互式）
│  优化 Agent      │  → 产出优化报告
│  (optimization)  │
└────────┬────────┘
         ↓ ⏸ 审批点 3：最终决策（接受 / 重做 / 回 Phase 1）
```

- **文件驱动状态转移**：STRATEGY_DESIGN.md → strategy.py → backtest_result.json → changelog.md
- **棘轮决策**：每次优化用 `score_strategy()` 评分，有效保留、无效回滚

## 适用市场

| 市场 | 数据源 | 交易规则 |
|------|--------|---------|
| **A股** | [FTShare](https://github.com/rivar0107/all-in-one)（免费） | T+1，涨跌停 ±10%/±20% |
| **港股** | FutuAPI（需 Futu OpenD） | T+0，无涨跌停 |
| **美股** | FutuAPI（需 Futu OpenD） | T+0，PDT 规则 |

> 期货、期权暂不支持，后续版本逐步加入。

## 快速开始

### 安装

```bash
npx skills add rivar0107/autostrategy --yes
```

安装后在 Claude Code / Gemini CLI / Copilot CLI 中直接使用，无需额外配置。

### 环境准备（可选）

```bash
pip install numpy pandas pyyaml
```

- **A股数据**：安装 [ftshare-all-in-one](https://github.com/rivar0107/all-in-one) Skill（免费）
- **港美股数据**：安装 FutuAPI Skill（需 [Futu OpenD](https://www.futunn.com/download/openAPI)）

### 使用示例

```
"帮我设计一个双均线交叉策略"
"我想做一个港股量化策略，但不清楚用什么方法"
"帮我根据某大V在微博上的投资观点做个量化策略"
"优化这个策略的回测结果，降低最大回撤"
```

## 项目结构

```
autostrategy/
├── SKILL.md                          # 调度台：入口分流 + Agent 编排 + 审批点控制
├── prompts/
│   ├── design_agent.md               # Phase 1：策略设计 Agent 指令
│   ├── codegen_agent.md              # Phase 2：代码生成 Agent 指令
│   └── optimization_agent.md         # Phase 3：自主优化 Agent 指令
├── scripts/
│   ├── env_setup.py                  # 环境检查与依赖安装
│   ├── quality_check.py              # 策略设计文档质量检查
│   └── run_backtest.py               # 回测执行与评分
├── examples/
│   └── dynamic-grid-multi-market/    # 示例：动态网格多标的策略
│       ├── STRATEGY_DESIGN.md
│       ├── config.yaml
│       ├── strategy.py
│       ├── requirements.txt
│       └── data/
│           └── fetch_data.py
└── skills-lock.json
```

## 示例策略

内置「动态网格多标的」策略示例，覆盖 5 个跨市场标的（腾讯、科创50ETF、中证2000ETF、小鹏、特斯拉）。

2024-2025 回测：年化收益 11.99%，最大回撤 30.47%，夏普 0.49，胜率 75.2%。

## 评估与设计原则

**评分函数**：5 个维度共 100 分 + 简洁性惩罚（条件数 > 10 时每个扣 1.5 分）。

| 维度 | 满分 | 满分条件 | 设计原则 |
|------|------|---------|---------|
| 年化收益率 | 25 | > 基准×2（沪深300 8% / 恒生 5% / 标普 10%）| 简洁性优先：分数提升必须大于复杂度增加 |
| 最大回撤 | 20 | < 10%（回撤≥30%得0分）| 文档是核心：所有逻辑先写入 DESIGN.md |
| 夏普比率 | 25 | > 2.0 | 人在回路：设计文档和回测结果人类确认 |
| 胜率 | 15 | > 60% | 量化评估：用 score_strategy() 决定 keep/revert |
| 盈亏比 | 15 | > 2.5 | 不推实盘：定位是策略创建和验证工具 |

同时检测：过拟合、幸存者偏差、未来函数、流动性、前后半段稳定性。

## 技术栈

- **语言**：Python 3.9+
- **数据处理**：NumPy, Pandas
- **数据源**：[FTShare](https://github.com/rivar0107/all-in-one)（A股）、FutuAPI（港美股）
- **AI Agent 兼容**：Claude Code, Gemini CLI, Copilot CLI, Codex, Cline 等

## 相关项目

- [all-in-one](https://github.com/rivar0107/all-in-one) — 免费的 A 股/港股行情数据 Skill
- [darwin-skill](https://github.com/alchaincyf/darwin-skill) — AI Skill 持续优化框架

## License

MIT License
