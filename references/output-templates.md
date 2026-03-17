# 输出模板

## 推荐输出

```
📊 双币投资推荐 — {日期}

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

━━ {金额} {COIN} → {低买/高卖} ━━
  {COIN} ${SPOT} | DVOL {dvol}%

  🥇 第1名: {低买/高卖} ${strike1} | {d1}天 | APR {apr1}% | Δ {delta1} | 得分 {score1}
  🥈 第2名: {低买/高卖} ${strike2} | {d2}天 | APR {apr2}% | Δ {delta2} | 得分 {score2}
  🥉 第3名: {低买/高卖} ${strike3} | {d3}天 | APR {apr3}% | Δ {delta3} | 得分 {score3}

被行权: 低买→接币切高卖 | 高卖→换U切低买
DYOR。
```

---

## 高卖模式附加信息

```
{高卖时}:
  成本线 ${COST_BASIS} | 行权获得 {数量} USDT

{DRAWDOWN_ALERT 时}:
🚨 现价较成本跌超 {%}！高卖停滞。评估: 止损换U 或 持币等反弹。

{NO_CALL_PRODUCT 时}:
⚠️ 暂无保本高卖产品，建议持币。
```

---

## 策略总结（停止时）

```
📋 策略总结

初始金额: ${初始}
当前金额: ${当前}
累计收益: {+/-}${收益} ({收益率}%)
操作次数: {n}次
胜率: {w/n}% (未行权视为胜)

已停止。说"双币"重新开始。
```

---

## 申购确认

```
✅ 申购成功

产品: {低买/高卖} ${strike} | {d}天
金额: ${amount}
预期收益: ${保费} (APR {apr}%)
到期日: {YYYY-MM-DD HH:MM} UTC

━━ 自动结算检查（OpenClaw）━━
到期后 1 小时将自动检查结算，运行以下命令启用：

openclaw cron add \
  --name "DCI结算检查-{record_id}" \
  --at "{ISO8601_UTC时间}" \
  --session isolated \
  --message "运行结算检查: python3 /path/to/positions.py --check --json --with-recommendations" \
  --announce
```

注意：所有时间均使用 UTC 时区，OpenClaw cron 的 `--at` 参数使用 ISO 8601 格式（如 `2024-03-20T09:00:00Z`）。

---

## JSON 输出格式（供 Agent 解析）

```json
{
  "USDT": {
    "mode": "PUT",
    "amount": 1000.0,
    "recommendations": [
      {
        "strikePrice": 80000,
        "duration": 3,
        "apr": 35.5,
        "delta": -0.08,
        "score": 443.75,
        "exercisedCoin": "BTC"
      }
    ]
  }
}
```
