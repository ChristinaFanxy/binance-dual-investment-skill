#!/usr/bin/env python3
"""
Dual Investment 数据抓取脚本
获取币安双币投资产品、Deribit Delta、现价和 DVOL
"""

import json
import hmac
import hashlib
import time
import math
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# 路径配置
SKILL_DIR = Path(__file__).parent.parent
DATA_FILE = SKILL_DIR / "data" / "market_data.json"
CONFIG_FILE = SKILL_DIR / "config.json"


def load_binance_config():
    """加载币安 API 配置"""
    if not CONFIG_FILE.exists():
        print(f"警告: 配置文件不存在 {CONFIG_FILE}")
        print("请创建配置文件，格式：")
        print('{"api_key": "your_key", "secret_key": "your_secret"}')
        return None, None

    with open(CONFIG_FILE) as f:
        config = json.load(f)
    return config.get("api_key"), config.get("secret_key")


def sign_request(params: dict, secret_key: str) -> str:
    """生成币安 API 签名"""
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


def fetch_json(url: str, headers: dict = None, retries: int = 3, delay: float = 1.0) -> dict:
    """通用 JSON 请求，带重试机制"""
    req = urllib.request.Request(url, headers=headers or {})
    last_error = None

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))  # 递增延迟

    print(f"请求失败 {url}: {last_error}")
    return {}


def norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数（近似）"""
    # Abramowitz and Stegun approximation
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x / 2)
    return 0.5 * (1.0 + sign * y)


def bs_delta(S: float, K: float, T: float, sigma: float, r: float = 0.05, option_type: str = "C") -> float:
    """Black-Scholes Delta 计算"""
    if T <= 0 or sigma <= 0:
        return 0.0

    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (sigma * math.sqrt(T))

    if option_type == "C":
        return norm_cdf(d1)
    else:  # PUT
        return norm_cdf(d1) - 1


def parse_instrument_name(name: str) -> dict:
    """解析 Deribit 合约名称，如 BTC-18MAR26-64000-C"""
    import re
    pattern = r"^(\w+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+)-([PC])$"
    match = re.match(pattern, name)
    if not match:
        return {}

    currency, day, month, year, strike, opt_type = match.groups()
    month_map = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }

    try:
        expiry = datetime(2000 + int(year), month_map[month], int(day), 8, 0, 0)  # UTC 8:00
        expiry_ms = int(expiry.timestamp() * 1000)
    except:
        return {}

    return {
        "currency": currency,
        "expiry_ms": expiry_ms,
        "strike": float(strike),
        "option_type": opt_type,
    }


def fetch_spot_prices() -> dict:
    """获取 BTC/ETH 现价（Deribit 指数价）"""
    prices = {}
    for coin in ["btc", "eth"]:
        url = f"https://www.deribit.com/api/v2/public/get_index_price?index_name={coin}_usd"
        data = fetch_json(url)
        if "result" in data:
            prices[coin.upper()] = data["result"]["index_price"]
    return prices


def fetch_dvol() -> dict:
    """获取 DVOL 波动率指数"""
    dvol = {}
    now_ms = int(time.time() * 1000)
    two_days_ago_ms = now_ms - 2 * 24 * 3600 * 1000

    for coin in ["BTC", "ETH"]:
        url = (
            f"https://www.deribit.com/api/v2/public/get_volatility_index_data"
            f"?currency={coin}&start_timestamp={two_days_ago_ms}"
            f"&end_timestamp={now_ms}&resolution=3600"
        )
        data = fetch_json(url)
        if "result" in data and data["result"].get("data"):
            dvol[coin] = data["result"]["data"][-1][4]
    return dvol


def fetch_binance_products(api_key: str, secret_key: str, max_duration: int = 7) -> list:
    """获取币安双币投资产品列表（分页获取，过滤期限）"""
    if not api_key or not secret_key:
        print("跳过币安产品获取（无 API Key）")
        return []

    products = []

    # PUT: 投入 USDT，行权得 BTC/ETH (exercisedCoin=BTC/ETH, investCoin=USDT)
    # CALL: 投入 BTC/ETH，行权得 USDT (exercisedCoin=USDT, investCoin=BTC/ETH)
    query_configs = [
        ("PUT", "BTC", "USDT"),   # 低买 BTC
        ("PUT", "ETH", "USDT"),   # 低买 ETH
        ("CALL", "USDT", "BTC"),  # 高卖 BTC
        ("CALL", "USDT", "ETH"),  # 高卖 ETH
    ]

    for option_type, exercised_coin, invest_coin in query_configs:
            page = 1
            while True:
                params = {
                    "optionType": option_type,
                    "exercisedCoin": exercised_coin,
                    "investCoin": invest_coin,
                    "pageSize": 100,
                    "pageIndex": page,
                    "timestamp": int(time.time() * 1000),
                }

                signature = sign_request(params, secret_key)
                params["signature"] = signature

                query = urllib.parse.urlencode(params)
                url = f"https://api.binance.com/sapi/v1/dci/product/list?{query}"

                headers = {
                    "X-MBX-APIKEY": api_key,
                    "User-Agent": "dual-investment-skill/3.0.0"
                }

                data = fetch_json(url, headers)

                # 处理返回格式
                product_list = []
                if isinstance(data, dict) and "list" in data:
                    product_list = data["list"]
                elif isinstance(data, list):
                    product_list = data

                if not product_list:
                    break

                for p in product_list:
                    duration = int(p.get("duration", 0))
                    if p.get("canPurchase") and duration <= max_duration:
                        # CALL: exercisedCoin=USDT, investCoin=BTC/ETH，但我们存储时统一用标的币种
                        # 即 CALL 的实际标的是 investCoin (BTC/ETH)
                        underlying = invest_coin if option_type == "CALL" else exercised_coin
                        products.append({
                            "id": p.get("id"),
                            "orderId": p.get("orderId"),
                            "optionType": option_type,
                            "exercisedCoin": underlying,  # 统一为标的币种 (BTC/ETH)
                            "investCoin": "USDT" if option_type == "PUT" else underlying,
                            "strikePrice": float(p.get("strikePrice", 0)),
                            "duration": duration,
                            "apr": float(p.get("apr", 0)) * 100,
                            "settleDate": int(p.get("settleDate", 0)),
                            "canPurchase": True,
                        })

                if len(product_list) < 100:
                    break
                page += 1
                time.sleep(0.2)  # 避免请求过快

    return products


def build_deribit_instrument_name(currency: str, expiry_ms: int, strike: float, option_type: str) -> str:
    """
    构建 Deribit 合约名称
    例如: BTC-21MAR26-74000-P
    """
    from datetime import datetime, timezone

    expiry_dt = datetime.fromtimestamp(expiry_ms / 1000, tz=timezone.utc)
    month_map = {1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
                 7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"}

    day = expiry_dt.day
    month = month_map[expiry_dt.month]
    year = expiry_dt.year % 100
    strike_int = int(strike)
    opt = "P" if option_type == "PUT" else "C"

    return f"{currency}-{day}{month}{year}-{strike_int}-{opt}"


def fetch_deribit_options_summary(max_days: int = 7) -> dict:
    """批量获取 Deribit 期权摘要，返回 {instrument_name: {currency, strike, expiry_ms, option_type}}"""
    options = {}
    now_ms = int(time.time() * 1000)
    max_expiry_ms = now_ms + max_days * 24 * 3600 * 1000

    for coin in ["BTC", "ETH"]:
        url = f"https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency={coin}&kind=option"
        data = fetch_json(url)

        for item in data.get("result", []):
            name = item.get("instrument_name", "")
            parsed = parse_instrument_name(name)
            if not parsed:
                continue
            # 过滤 max_days 天内到期
            if parsed["expiry_ms"] > max_expiry_ms:
                continue
            options[name] = parsed

    return options


def match_binance_to_deribit(binance_products: list, deribit_options: dict) -> list:
    """匹配币安产品与 Deribit 期权，返回需要请求 delta 的合约列表"""
    matched = set()

    for product in binance_products:
        coin = product["exercisedCoin"]
        strike = product["strikePrice"]
        settle_ms = product["settleDate"]
        opt_type = product["optionType"]

        for name, info in deribit_options.items():
            if info["currency"] != coin:
                continue
            if info["option_type"] != ("P" if opt_type == "PUT" else "C"):
                continue
            if abs(info["strike"] - strike) > 0.01:
                continue
            # 到期日差异在 1 天内
            if abs(info["expiry_ms"] - settle_ms) <= 86400 * 1000:
                matched.add(name)

    return list(matched)


def fetch_single_delta(instrument: str) -> tuple[str, float | None]:
    """获取单个合约的 Delta"""
    url = f"https://www.deribit.com/api/v2/public/ticker?instrument_name={instrument}"
    data = fetch_json(url)
    if "result" in data and "greeks" in data["result"]:
        delta = data["result"]["greeks"].get("delta")
        if delta is not None:
            return (instrument, round(delta, 5))
    return (instrument, None)


def fetch_deribit_deltas_for_products(binance_products: list) -> dict:
    """获取匹配的 Deribit 期权 Delta（并发请求）"""
    if not binance_products:
        print("  无币安产品，跳过 Delta 获取")
        return {}

    # 1. 批量获取 Deribit 期权摘要
    print("  获取 Deribit 期权列表...")
    deribit_options = fetch_deribit_options_summary(max_days=7)
    print(f"  Deribit 7天内期权: {len(deribit_options)} 个")

    # 2. 匹配币安产品
    matched = match_binance_to_deribit(binance_products, deribit_options)
    print(f"  匹配到 {len(matched)} 个合约")

    # 3. 并发请求 ticker 获取精确 delta
    deltas = {}
    if not matched:
        return deltas

    max_workers = min(10, len(matched))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_single_delta, inst): inst for inst in matched}
        for future in as_completed(futures):
            instrument, delta = future.result()
            if delta is not None:
                deltas[instrument] = delta

    print(f"  成功获取 {len(deltas)} 个 Delta")
    return deltas


def main():
    print("开始获取市场数据...")

    # 加载配置
    api_key, secret_key = load_binance_config()

    # 并发获取现价和 DVOL
    print("获取现价和 DVOL...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        spot_future = executor.submit(fetch_spot_prices)
        dvol_future = executor.submit(fetch_dvol)
        spot_prices = spot_future.result()
        dvol = dvol_future.result()
    print(f"  BTC: ${spot_prices.get('BTC', 'N/A')}, ETH: ${spot_prices.get('ETH', 'N/A')}")
    print(f"  BTC DVOL: {dvol.get('BTC', 'N/A')}%, ETH DVOL: {dvol.get('ETH', 'N/A')}%")

    print("获取币安双币投资产品...")
    binance_products = fetch_binance_products(api_key, secret_key)
    print(f"  找到 {len(binance_products)} 个可购买产品")

    print("计算 Deribit Delta（只查询匹配的合约）...")
    deribit_deltas = fetch_deribit_deltas_for_products(binance_products)
    print(f"  共 {len(deribit_deltas)} 个期权 Delta")

    # 组装数据
    market_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "spot_prices": spot_prices,
        "dvol": dvol,
        "binance_products": binance_products,
        "deribit_deltas": deribit_deltas,
    }

    # 保存
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(market_data, f, indent=2, ensure_ascii=False)

    print(f"\n数据已保存到 {DATA_FILE}")
    print(f"更新时间: {market_data['updated_at']}")


if __name__ == "__main__":
    main()
