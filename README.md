# 币安双币投资 Delta 智能顾问

BTC/ETH 双币投资车轮策略工具，基于 Deribit Delta 定价 + 币安真实 APR。

## 功能

- 账户余额扫描（现货 + 资金账户）
- Delta 风控评分推荐
- 一键申购
- 结算追踪 + 收益计算
- 车轮策略自动切换建议

## 安装

Clone 到任意目录：
```bash
git clone https://github.com/ChristinaFanxy/binance-dual-investment-skill.git
cd binance-dual-investment-skill

# 配置 API Key
cp config.example.json config.json
# 编辑 config.json 填入你的币安 API Key

# 创建数据目录
mkdir -p data
```

## 命令行使用

所有脚本支持独立运行，不依赖任何 agent 框架：

```bash
# 检查 API 配置
python3 scripts/binance_api.py --check

# 扫描账户余额
python3 scripts/account.py --scan

# 获取市场数据
python3 scripts/fetch_data.py

# 获取推荐（单币种）
python3 scripts/calc_score.py --mode PUT --coin BTC

# 获取推荐（多币种）
python3 scripts/calc_score.py --funds "1000 USDT + 0.5 ETH"

# 查看持仓
python3 scripts/positions.py --list

# 检查结算（JSON 输出）
python3 scripts/positions.py --check --json
```

## Agent 集成

### Claude Code

复制到 skills 目录：
```bash
cp -r binance-dual-investment-skill ~/.claude/skills/dual-investment
```

触发词：`双币`、`低买`、`高卖`、`推荐`、`Delta`

### OpenClaw / Codex / 其他 Agent

直接调用 Python 脚本，解析 JSON 输出：

```bash
# 获取推荐（JSON）
python3 /path/to/scripts/calc_score.py --funds "1000 USDT" --json

# 检查结算 + 下轮推荐（JSON）
python3 /path/to/scripts/positions.py --check --json --with-recommendations
```

JSON 输出结构：
```json
{
  "settlements": [{
    "id": "uuid",
    "exercised": true,
    "profit": {"premium_earned": 5.48, "pnl": -12.50},
    "wheel_suggestion": {"next_mode": "CALL"}
  }],
  "next_recommendations": [{
    "mode": "CALL",
    "coin": "BTC",
    "strike": 82000,
    "apr": 15.5,
    "score": 155.0
  }]
}
```

### 定时任务

```bash
# crontab -e
# 每天 9:00 检查结算
0 9 * * * python3 /path/to/scripts/positions.py --check --json >> /var/log/dci.log
```

## 文件结构

```
binance-dual-investment-skill/
├── SKILL.md              # Claude Code Skill 定义
├── config.example.json   # 配置模板
├── scripts/
│   ├── binance_api.py    # API 封装
│   ├── account.py        # 账户扫描
│   ├── fetch_data.py     # 数据获取
│   ├── calc_score.py     # 评分计算
│   ├── subscribe.py      # 申购执行
│   └── positions.py      # 持仓管理
├── references/
│   ├── api-endpoints.md  # API 文档
│   └── output-templates.md
└── data/                 # 运行时数据（gitignore）
```

## 安全

- API Key 存储在本地 config.json（已 gitignore）
- 主网操作需输入 CONFIRM 确认
- 不构成投资建议，DYOR

## License

MIT
