# API 端点文档

## 币安现货账户 API

### 账户余额

```
GET /api/v3/account
```

需要签名。返回所有资产余额。

响应字段：
- `balances`: 资产数组
  - `asset`: 币种名称
  - `free`: 可用余额
  - `locked`: 锁定余额

---

## 币安双币投资 API

### 产品列表

```
GET /sapi/v1/dci/product/list
```

需要签名。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| optionType | STRING | 是 | PUT 或 CALL |
| exercisedCoin | STRING | 是 | BTC 或 ETH |
| investCoin | STRING | 是 | USDT（PUT）或 BTC/ETH（CALL） |
| pageSize | INT | 否 | 每页数量，默认 100 |
| pageIndex | INT | 否 | 页码，从 1 开始 |
| timestamp | LONG | 是 | 毫秒时间戳 |
| signature | STRING | 是 | HMAC SHA256 签名 |

响应字段：
- `id`: 产品 ID
- `orderId`: 订单 ID
- `strikePrice`: 行权价
- `duration`: 天数
- `apr`: 年化收益率（小数）
- `settleDate`: 到期时间戳（毫秒）
- `canPurchase`: 是否可购买

### 申购

```
POST /sapi/v1/dci/product/subscribe
```

需要签名。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | STRING | 是 | 产品 ID |
| orderId | STRING | 是 | 订单 ID |
| depositAmount | DECIMAL | 是 | 申购金额 |
| timestamp | LONG | 是 | 毫秒时间戳 |
| signature | STRING | 是 | HMAC SHA256 签名 |

### 持仓查询

```
GET /sapi/v1/dci/product/positions
```

需要签名。返回所有双币投资持仓。

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | STRING | 否 | 筛选状态 |
| timestamp | LONG | 是 | 毫秒时间戳 |
| signature | STRING | 是 | HMAC SHA256 签名 |

状态值：
- `PENDING`: 待生效
- `PURCHASE_SUCCESS`: 申购成功
- `SETTLED`: 已结算

---

## Deribit 公开 API

### 指数价格

```
GET /api/v2/public/get_index_price
```

| 参数 | 说明 |
|------|------|
| index_name | btc_usd 或 eth_usd |

### 期权汇总

```
GET /api/v2/public/get_book_summary_by_currency
```

| 参数 | 说明 |
|------|------|
| currency | BTC 或 ETH |
| kind | option |

### 期权 Ticker

```
GET /api/v2/public/ticker
```

| 参数 | 说明 |
|------|------|
| instrument_name | 合约名称，如 BTC-17MAR26-80000-P |

响应包含 `greeks.delta`。

### DVOL 波动率指数

```
GET /api/v2/public/get_volatility_index_data
```

| 参数 | 说明 |
|------|------|
| currency | BTC 或 ETH |
| start_timestamp | 开始时间（毫秒） |
| end_timestamp | 结束时间（毫秒） |
| resolution | 3600（小时） |

响应 `data` 数组，每条记录 index 4 为收盘 DVOL。

---

## 币安 API 签名流程

### 配置文件

路径: `~/.claude/skills/dual-investment/config.json`

```json
{
  "api_key": "your_api_key",
  "secret_key": "your_secret_key",
  "max_drawdown_alert": 0.30
}
```

### 签名步骤

1. 拼接所有参数为 query string（按字母序）
2. 使用 RFC 3986 编码
3. 用 secret_key 做 HMAC SHA256 签名
4. 将签名追加到参数中

### Python 示例

```python
import hmac
import hashlib
import urllib.parse
import time

def sign_request(params: dict, secret_key: str) -> str:
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature

# 使用示例
params = {
    "optionType": "PUT",
    "exercisedCoin": "BTC",
    "investCoin": "USDT",
    "timestamp": int(time.time() * 1000),
}
params["signature"] = sign_request(params, secret_key)
```

### curl 示例

```bash
TIMESTAMP=$(date +%s000)
QUERY="optionType=PUT&exercisedCoin=BTC&investCoin=USDT&timestamp=$TIMESTAMP"
SIGNATURE=$(echo -n "$QUERY" | openssl dgst -sha256 -hmac "$SECRET_KEY" | cut -d' ' -f2)

curl -H "X-MBX-APIKEY: $API_KEY" \
     -H "User-Agent: dual-investment-skill/3.0.0" \
     "https://api.binance.com/sapi/v1/dci/product/list?$QUERY&signature=$SIGNATURE"
```

### Header 要求

| Header | 说明 |
|--------|------|
| X-MBX-APIKEY | API Key（必填） |
| User-Agent | 建议设置，避免被限流 |
