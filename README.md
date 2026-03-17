# 币安双币投资 Delta 智能顾问

BTC/ETH 双币投资车轮策略工具，基于 Deribit Delta 定价 + 币安真实 APR。

## 功能

- 账户余额扫描（现货 + 资金账户）
- Delta 风控评分推荐
- 一键申购
- 结算追踪 + 收益计算
- 车轮策略自动切换建议

## 安装

1. 复制到 Claude Code skills 目录：
```bash
cp -r dual-investment ~/.claude/skills/
```

2. 配置 API Key：
```bash
cd ~/.claude/skills/dual-investment
cp config.example.json config.json
# 编辑 config.json 填入你的币安 API Key
```

3. 确保 data 目录存在：
```bash
mkdir -p ~/.claude/skills/dual-investment/data
```

## 使用

在 Claude Code 中说：
- "双币" - 触发完整流程
- "低买" / "高卖" - 指定模式
- "推荐" - 获取当前推荐
- "Delta" - 查看 Delta 分析

## OpenClaw 集成

定时结算检查：
```bash
python3 ~/.claude/skills/dual-investment/scripts/positions.py --check --json
```

输出 JSON 格式供解析，包含：
- `settlements` - 结算结果
- `next_recommendations` - 下轮推荐

## 文件结构

```
dual-investment/
├── SKILL.md              # Skill 定义
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
