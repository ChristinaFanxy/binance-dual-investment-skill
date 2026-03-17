---
name: dual-investment
description: |
  BTC/ETH 币安双币投资 Delta 智能顾问。Deribit 预言机打价 + 币安真实 APR，车轮策略全闭环。
  触发词: "双币"、"低买"、"高卖"、"推荐"、"Delta"
---

# 执行流程

所有浮点运算、日期处理在 Python 脚本中完成。

## Phase 0: API 配置检查

**检查配置**: 读取 `config.json`，若 `api_key` 为 `your_api_key` 则输出配置指南并停止。

```bash
python3 scripts/binance_api.py --check
```

---

## Phase 1: 账户扫描

**扫描余额**: 显示 USDT/USDC/ETH/BTC 可用余额。

```bash
python3 scripts/account.py --scan
```

**用户输入投资金额**，支持格式：
- `1000 USDT` - 单币种
- `1000 USDT + 0.5 ETH + 0.3 BTC` - 多币种组合
- `all USDT` - 全部可用
- `50% BTC` - 百分比

记录 `FUNDS`（投资金额映射）。

---

## Phase 2: 策略推荐与申购

**检查数据时效**: 读取 `data/market_data.json`，若 `updated_at` 超过 1 小时则运行：
```bash
python3 scripts/fetch_data.py
```

**获取推荐**:
```bash
python3 scripts/calc_score.py --funds "1000 USDT + 0.5 ETH"
```

**模式自动判断**:
- USDT/USDC → PUT（低买）
- BTC/ETH → CALL（高卖）

**成本价防御**（CALL 模式）:
- 从持仓历史取最近 PUT 行权价作为 `COST_BASIS`
- `DRAWDOWN = (COST_BASIS - SPOT) / COST_BASIS`
- 若 `DRAWDOWN >= MAX_DRAWDOWN_ALERT` → 标记警告

**申购确认**: 用户输入 `CONFIRM` 后执行真实申购。

```bash
# 申购记录保存到 data/subscriptions.json
```

---

## Phase 2.5: 设置结算检查（可选）

申购成功后，脚本会输出 OpenClaw cron 命令。

**OpenClaw 用户**：直接运行输出的命令，到期后自动检查结算
**其他 Agent**：到期后手动运行 `python3 scripts/positions.py --check`

---

## Phase 3: 行权检查与复投

**检查待结算持仓**:
```bash
python3 scripts/positions.py --check
```

**行权判断**:
| 类型 | 行权条件 | 结果 | 下一步 |
|------|----------|------|--------|
| PUT | 现价 ≤ 行权价 | USDT → BTC/ETH | 切换 CALL |
| PUT | 现价 > 行权价 | 返还 USDT + 保费 | 继续 PUT |
| CALL | 现价 ≥ 行权价 | BTC/ETH → USDT | 切换 PUT |
| CALL | 现价 < 行权价 | 返还 BTC/ETH + 保费 | 继续 CALL |

**复投**: 询问用户是否复投，回到 Phase 1。

---

## 筛选条件

| 条件 | 说明 |
|------|------|
| optionType | 匹配投资币种模式 |
| canPurchase | true |
| duration | 1-5 天 |
| apr | ≥ 3% |
| strikePrice | CALL 时 ≥ COST_BASIS |

---

## Delta 匹配与风控

**匹配 Delta**: 从 `deribit_deltas` 找行权价相同、到期最近的合约。

**相对期限熔断**: `误差比 = |deribit_expiry - binance_settle| / (duration × 86400000)`，超过 0.5 则废弃。

**DVOL 风控**:
| DVOL | Delta 上限 |
|------|----------|
| > 70 | 0.15 |
| 40-70 | 0.30 |
| < 40 | 0.35 |

剔除 |Delta| < 0.05 的产品。

---

## 评分公式

```
SCORE = APR / max(|Delta|, 0.01)
```

取 Top 1 推荐 + Top 2 备选。

---

## 脚本说明

| 脚本 | 功能 |
|------|------|
| `binance_api.py` | 币安 API 封装（余额、申购、持仓） |
| `account.py` | 账户扫描、资金输入解析 |
| `fetch_data.py` | 获取市场数据 |
| `calc_score.py` | 评分计算、多币种推荐 |
| `subscribe.py` | 申购执行、记录保存 |
| `positions.py` | 持仓查询、行权检查 |

---

## 安全规则

1. Key 显示: API 前5+后4，Secret 仅后5
2. 主网操作必须输入 `CONFIRM`
3. 不编造 Delta/APR — 全部来自 JSON 或 API
4. 不构成投资建议，DYOR

---

## Agent 约束

1. 浮点/日期/排序全部 Python，禁止 Bash 算术
2. 高卖时行权价 ≥ 成本价，无例外
3. Delta 除零保护: `max(|Delta|, 0.01)`
4. 仓位隔离: 只操作策略内资金
5. 数据来源: 必须来自 `data/market_data.json`
6. 停止触发词: "停"、"停止"、"暂停"、"退出"、"stop" → 输出策略总结
