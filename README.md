# 币安双币投资 Delta 智能顾问

基于 Deribit Delta 定价 + 币安真实 APR 的 BTC/ETH 双币投资车轮策略工具。

## 项目背景

### 什么是双币投资？

双币投资（Dual Investment）是一种结构化理财产品，本质是**卖出期权**：

- **低买（Sell Put）**：投入 USDT，若到期时现价 ≤ 行权价，则以行权价买入 BTC/ETH；否则返还 USDT + 保费
- **高卖（Sell Call）**：投入 BTC/ETH，若到期时现价 ≥ 行权价，则以行权价卖出换 USDT；否则返还币 + 保费

### 车轮策略（Wheel Strategy）

车轮策略是一种循环操作：

```
USDT → 低买 PUT → 行权得币 → 高卖 CALL → 行权得 USDT → 循环
         ↓                      ↓
      未行权返还 USDT        未行权返还币
      （继续低买）           （继续高卖）
```

无论行权与否，每轮都能赚取保费收益。

### 为什么需要 Delta？

币安双币投资只显示 APR，不显示行权概率。**高 APR 往往意味着高行权风险**。

Delta 是期权的希腊字母之一，表示标的价格变动 $1 时期权价格的变动量，同时也近似于**行权概率**：

- |Delta| = 0.10 → 约 10% 行权概率
- |Delta| = 0.30 → 约 30% 行权概率
- |Delta| = 0.50 → 约 50% 行权概率（平值期权）

本工具从 Deribit 获取专业期权市场的 Delta 数据，为币安产品提供风险定价参考。

---

## 核心功能

### 1. 多钱包余额扫描

支持币安现货账户 + 资金账户的统一扫描：

```bash
python3 scripts/account.py --scan
```

输出示例：
```
📊 账户余额扫描

USDT: 1,000.00 (现货: 0.00 | 资金: 1,000.00)
BTC:  0.05000000 (现货: 0.05 | 资金: 0.00)
ETH:  0.5000 (现货: 0.50 | 资金: 0.00)
```

### 2. 市场数据获取

从多个数据源获取实时数据：

```bash
python3 scripts/fetch_data.py
```

数据来源：
| 数据 | 来源 | 用途 |
|------|------|------|
| BTC/ETH 现价 | Deribit Index | 统一定价基准 |
| DVOL 波动率指数 | Deribit | 动态风控阈值 |
| 双币产品列表 | 币安 API | 可申购产品 |
| 期权 Delta | Deribit | 行权概率估算 |

### 3. 智能产品筛选与评分

```bash
python3 scripts/calc_score.py --funds "1000 USDT"
```

#### 筛选条件

| 条件 | 规则 | 原因 |
|------|------|------|
| 期限 | 1-5 天 | 短期产品流动性好，便于车轮滚动 |
| APR | ≥ 3% | 过滤收益过低的产品 |
| Delta 下限 | \|Δ\| ≥ 0.05 | 过滤深度虚值（收益太低） |
| Delta 上限 | 动态（见下表） | 控制行权风险 |
| 可购买状态 | canPurchase = true | 确保产品可申购 |
| 成本价保护 | 高卖行权价 ≥ 成本价 | 防止亏本卖出 |

#### DVOL 动态风控

根据市场波动率动态调整 Delta 上限：

| DVOL 区间 | Delta 上限 | 风控逻辑 |
|-----------|-----------|----------|
| > 70% | 0.15 | 高波动市场，收紧风控 |
| 40-70% | 0.30 | 正常市场，标准风控 |
| < 40% | 0.35 | 低波动市场，适度放宽 |

#### 评分公式

```
Score = APR / |Delta|
```

**设计思路**：
- APR 越高 → 收益越好 → 分数越高
- |Delta| 越低 → 行权概率越低 → 风险越小 → 分数越高
- 综合考量收益与风险的性价比

**示例**：
| 产品 | APR | Delta | Score | 解读 |
|------|-----|-------|-------|------|
| A | 30% | -0.10 | 300 | 中等收益，低风险 |
| B | 20% | -0.05 | 400 | 低收益，极低风险 ✓ 最优 |
| C | 50% | -0.25 | 200 | 高收益，高风险 |

### 4. Delta 匹配算法

币安产品与 Deribit 期权的匹配逻辑：

```python
匹配条件：
1. 币种相同（BTC/ETH）
2. 期权类型相同（PUT/CALL）
3. 行权价相同（误差 < 0.01）
4. 到期日接近（相对误差 < 50%）

Fallback：
若无匹配，使用 Black-Scholes 公式计算理论 Delta
```

#### 相对期限熔断

```
误差比 = |Deribit到期 - 币安结算| / (duration × 86400000)
若误差比 > 0.5 → 废弃该匹配
```

### 5. 一键申购

```bash
python3 scripts/subscribe.py --product-id XXX --amount 1000
```

安全机制：
- 主网操作需输入 `CONFIRM` 确认
- 自动记录申购到 `data/subscriptions.json`
- 支持从资金账户自动划转到现货账户

### 6. 结算追踪与收益计算

```bash
python3 scripts/positions.py --check --json
```

#### 收益计算逻辑

```python
保费收入 = 投资金额 × APR × 期限 / 365

PUT 行权：
  获得币数 = 投资金额 / 行权价
  市值 = 获得币数 × 现价
  盈亏 = 市值 - 投资金额 + 保费

PUT 未行权：
  盈亏 = 保费（纯收益）

CALL 行权：
  获得 USDT = 投资币数 × 行权价
  盈亏 = 获得 USDT - (投资币数 × 现价) + 保费

CALL 未行权：
  盈亏 = 保费（以币本位计）
```

#### JSON 输出结构

```json
{
  "timestamp": "2024-03-18T09:00:00Z",
  "settlements": [{
    "id": "uuid",
    "option_type": "PUT",
    "strike_price": 80000,
    "settle_price": 79500,
    "exercised": true,
    "profit": {
      "premium_earned": 5.48,
      "pnl": -12.50,
      "total_return_pct": -0.7
    },
    "wheel_suggestion": {
      "next_mode": "CALL",
      "reason": "低买行权成功，建议高卖赚取保费"
    }
  }],
  "next_recommendations": [...]
}
```

---

## 输出示例

```
📊 双币投资推荐 — 2024-03-17 22:35

━━ 筛选条件 ━━
  期限: 1-5 天
  APR: ≥ 3%
  Delta: 0.05 ~ 动态上限 (根据 DVOL 调整)
    DVOL > 70% → Delta ≤ 0.15
    DVOL 40-70% → Delta ≤ 0.30
    DVOL < 40% → Delta ≤ 0.35

━━ 评分公式 ━━
  Score = APR / |Delta|
  APR 越高、Delta 越低 → 得分越高

━━ 1,000.00 USDT → 低买 ━━
  BTC $84,000 | DVOL 52.3%

  🥇 第1名: 低买 $78,000 | 3天 | APR 35.5% | Δ -0.08 | 得分 443.8
  🥈 第2名: 低买 $76,000 | 2天 | APR 28.2% | Δ -0.06 | 得分 470.0
  🥉 第3名: 低买 $80,000 | 1天 | APR 42.1% | Δ -0.12 | 得分 350.8

被行权: 低买→接币切高卖 | 高卖→换U切低买
DYOR。
```

---

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户 / Agent                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    calc_score.py                            │
│              (评分计算 + 输出格式化)                          │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  fetch_data.py  │ │  account.py     │ │  positions.py   │
│  (数据获取)      │ │  (余额扫描)      │ │  (持仓管理)      │
└─────────────────┘ └─────────────────┘ └─────────────────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    binance_api.py                           │
│              (币安 API 统一封装)                              │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│      Binance API        │     │      Deribit API        │
│  - 账户余额              │     │  - 指数价格              │
│  - 双币产品列表          │     │  - DVOL 波动率           │
│  - 申购/持仓             │     │  - 期权 Delta            │
└─────────────────────────┘     └─────────────────────────┘
```

---

## 安装与配置

### 1. 克隆仓库

```bash
git clone https://github.com/ChristinaFanxy/binance-dual-investment-skill.git
cd binance-dual-investment-skill
```

### 2. 配置 API Key

```bash
cp config.example.json config.json
```

编辑 `config.json`：
```json
{
  "api_key": "你的币安API Key",
  "secret_key": "你的币安Secret Key",
  "max_drawdown_alert": 0.30
}
```

API 权限要求：
- 读取账户信息
- 双币投资申购权限
- 资金划转权限（可选，用于自动从资金账户划转）

### 3. 创建数据目录

```bash
mkdir -p data
```

---

## 使用方式

### 命令行独立使用

```bash
# 完整流程
python3 scripts/binance_api.py --check      # 1. 检查 API 配置
python3 scripts/account.py --scan           # 2. 扫描余额
python3 scripts/fetch_data.py               # 3. 获取市场数据
python3 scripts/calc_score.py --funds "1000 USDT"  # 4. 获取推荐
python3 scripts/positions.py --check        # 5. 检查结算
```

### Claude Code 集成

复制到 skills 目录后，使用触发词：
- `双币` - 完整流程
- `低买` / `高卖` - 指定模式
- `推荐` - 获取当前推荐

### OpenClaw 集成

安装到 `~/.openclaw/skills` 目录：

```bash
git clone https://github.com/ChristinaFanxy/binance-dual-investment-skill.git ~/.openclaw/skills/dual-investment
```

使用触发词与 Claude Code 相同：`双币`、`低买`、`高卖`、`推荐`

### 其他 Agent（Codex 等）

调用脚本并解析 JSON 输出：

```bash
# 获取推荐
python3 scripts/calc_score.py --funds "1000 USDT" --json

# 检查结算 + 下轮推荐
python3 scripts/positions.py --check --json --with-recommendations
```

### 定时任务

```bash
# crontab -e
# 每天 9:00 检查结算
0 9 * * * cd /path/to/skill && python3 scripts/positions.py --check --json >> /var/log/dci.log
```

### OpenClaw 自动结算检查

申购成功后，脚本会自动输出 OpenClaw cron 命令。运行该命令可在到期后 1 小时自动检查结算：

```bash
# 申购成功后输出示例：
openclaw cron add \
  --name "DCI结算检查-abc12345" \
  --at "2024-03-20T09:00:00Z" \
  --session isolated \
  --message "运行结算检查: python3 /path/to/positions.py --check --json --with-recommendations" \
  --announce

# 查看已设置的定时任务
openclaw cron list

# 删除定时任务
openclaw cron remove --name "DCI结算检查-abc12345"
```

---

## 文件结构

```
binance-dual-investment-skill/
├── README.md                 # 项目文档
├── SKILL.md                  # Claude Code Skill 定义
├── config.example.json       # 配置模板
├── scripts/
│   ├── binance_api.py        # 币安 API 封装（余额、申购、持仓）
│   ├── account.py            # 账户扫描、资金输入解析
│   ├── fetch_data.py         # 市场数据获取（现价、DVOL、产品、Delta）
│   ├── calc_score.py         # 评分计算、筛选、排名
│   ├── subscribe.py          # 申购执行、记录保存
│   └── positions.py          # 持仓查询、结算检查、收益计算
├── references/
│   ├── api-endpoints.md      # API 端点文档
│   └── output-templates.md   # 输出模板参考
└── data/                     # 运行时数据（gitignore）
    ├── market_data.json      # 缓存的市场数据
    └── subscriptions.json    # 申购记录
```

---

## 安全说明

1. **API Key 保护**：`config.json` 已加入 `.gitignore`，不会上传到 GitHub
2. **显示脱敏**：API Key 显示为 `xxxxx...xxxx` 格式
3. **操作确认**：主网申购需输入 `CONFIRM` 确认
4. **风险提示**：本工具不构成投资建议，DYOR（Do Your Own Research）

---

## 技术亮点

1. **跨平台数据融合**：结合币安产品数据 + Deribit 专业期权定价
2. **动态风控**：根据 DVOL 自动调整 Delta 阈值
3. **智能评分**：APR/Delta 比值量化收益风险比
4. **车轮策略闭环**：自动建议下一轮操作方向
5. **多 Agent 兼容**：JSON 输出支持任意 Agent 框架集成
6. **多钱包支持**：自动扫描现货 + 资金账户

---

## License

MIT
