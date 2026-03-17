#!/usr/bin/env python3
"""
币安 API 统一封装
提供余额查询、双币投资申购、持仓查询功能
"""

import json
import hmac
import hashlib
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional

SKILL_DIR = Path(__file__).parent.parent
CONFIG_FILE = SKILL_DIR / "config.json"

# 支持的币种
SUPPORTED_COINS = ["USDT", "USDC", "ETH", "BTC"]


def load_config() -> dict:
    """加载配置文件"""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_credentials() -> tuple[Optional[str], Optional[str]]:
    """获取 API 凭证"""
    config = load_config()
    api_key = config.get("api_key")
    secret_key = config.get("secret_key")

    # 检查是否为占位符
    if api_key == "your_api_key" or not api_key:
        return None, None
    return api_key, secret_key


def sign_request(params: dict, secret_key: str) -> str:
    """生成 HMAC SHA256 签名"""
    query_string = urllib.parse.urlencode(params)
    signature = hmac.new(
        secret_key.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return signature


def api_request(
    method: str,
    endpoint: str,
    params: dict = None,
    signed: bool = True,
    retries: int = 3
) -> dict:
    """
    通用 API 请求

    Args:
        method: GET 或 POST
        endpoint: API 路径，如 /api/v3/account
        params: 请求参数
        signed: 是否需要签名
        retries: 重试次数

    Returns:
        API 响应 dict，失败返回 {"error": "..."}
    """
    api_key, secret_key = get_credentials()

    if signed and (not api_key or not secret_key):
        return {"error": "API 凭证未配置，请检查 config.json"}

    params = params or {}

    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["signature"] = sign_request(params, secret_key)

    query = urllib.parse.urlencode(params)
    url = f"https://api.binance.com{endpoint}"

    if method == "GET" and query:
        url = f"{url}?{query}"

    headers = {
        "User-Agent": "dual-investment-skill/3.0.0"
    }
    if api_key:
        headers["X-MBX-APIKEY"] = api_key

    last_error = None
    for attempt in range(retries):
        try:
            if method == "POST":
                data = query.encode("utf-8")
                req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            else:
                req = urllib.request.Request(url, headers=headers)

            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else str(e)
            try:
                error_json = json.loads(error_body)
                last_error = f"HTTP {e.code}: {error_json.get('msg', error_body)}"
            except:
                last_error = f"HTTP {e.code}: {error_body}"
        except Exception as e:
            last_error = str(e)

        if attempt < retries - 1:
            time.sleep(1 * (attempt + 1))

    return {"error": last_error}


def get_spot_balance(coins: list = None) -> dict:
    """
    获取现货账户余额

    Args:
        coins: 要查询的币种列表，默认 SUPPORTED_COINS

    Returns:
        {
            "USDT": {"free": 1000.0, "locked": 0.0},
            "BTC": {"free": 0.5, "locked": 0.0},
            ...
        }
        失败返回 {"error": "..."}
    """
    coins = coins or SUPPORTED_COINS

    result = api_request("GET", "/api/v3/account")

    if "error" in result:
        return result

    balances = {}
    for asset in result.get("balances", []):
        symbol = asset.get("asset")
        if symbol in coins:
            balances[symbol] = {
                "free": float(asset.get("free", 0)),
                "locked": float(asset.get("locked", 0))
            }

    # 确保所有请求的币种都有返回
    for coin in coins:
        if coin not in balances:
            balances[coin] = {"free": 0.0, "locked": 0.0}

    return balances


def get_funding_balance(coins: list = None) -> dict:
    """
    获取资金账户余额 (Funding Wallet)

    Args:
        coins: 要查询的币种列表，默认 SUPPORTED_COINS

    Returns:
        {
            "USDT": {"free": 1000.0, "locked": 0.0},
            ...
        }
        失败返回 {"error": "..."}
    """
    coins = coins or SUPPORTED_COINS

    result = api_request("POST", "/sapi/v1/asset/get-funding-asset", {})

    if "error" in result:
        return result

    balances = {}
    if isinstance(result, list):
        for asset in result:
            symbol = asset.get("asset")
            if symbol in coins:
                balances[symbol] = {
                    "free": float(asset.get("free", 0)),
                    "locked": float(asset.get("locked", 0))
                }

    # 确保所有请求的币种都有返回
    for coin in coins:
        if coin not in balances:
            balances[coin] = {"free": 0.0, "locked": 0.0}

    return balances


def get_all_balances(coins: list = None) -> dict:
    """
    获取所有账户余额（现货 + 资金账户）

    Args:
        coins: 要查询的币种列表，默认 SUPPORTED_COINS

    Returns:
        {
            "USDT": {"free": 1000.0, "locked": 0.0, "spot": 0.0, "funding": 1000.0},
            ...
        }
        失败返回 {"error": "..."}
    """
    coins = coins or SUPPORTED_COINS

    spot = get_spot_balance(coins)
    if "error" in spot:
        return spot

    funding = get_funding_balance(coins)
    if "error" in funding:
        return funding

    # 合并余额
    balances = {}
    for coin in coins:
        spot_free = spot.get(coin, {}).get("free", 0)
        spot_locked = spot.get(coin, {}).get("locked", 0)
        funding_free = funding.get(coin, {}).get("free", 0)
        funding_locked = funding.get(coin, {}).get("locked", 0)

        balances[coin] = {
            "free": spot_free + funding_free,
            "locked": spot_locked + funding_locked,
            "spot": spot_free,
            "funding": funding_free,
        }

    return balances


def subscribe_dci(product_id: str, order_id: str, amount: float) -> dict:
    """
    申购双币投资产品

    Args:
        product_id: 产品 ID
        order_id: 订单 ID
        amount: 申购金额

    Returns:
        成功返回 API 响应，失败返回 {"error": "..."}
    """
    params = {
        "id": product_id,
        "orderId": order_id,
        "depositAmount": str(amount),
    }

    return api_request("POST", "/sapi/v1/dci/product/subscribe", params)


def get_dci_positions(status: str = None) -> list:
    """
    获取双币投资持仓

    Args:
        status: 筛选状态 (PENDING, PURCHASE_SUCCESS, SETTLED 等)

    Returns:
        持仓列表，失败返回 []
    """
    params = {}
    if status:
        params["status"] = status

    result = api_request("GET", "/sapi/v1/dci/product/positions", params)

    if "error" in result:
        print(f"获取持仓失败: {result['error']}")
        return []

    # 处理返回格式
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "list" in result:
        return result["list"]

    return []


def check_api_config() -> dict:
    """
    检查 API 配置状态

    Returns:
        {
            "configured": bool,
            "api_key_preview": "xxxxx...xxxx" or None,
            "message": str
        }
    """
    api_key, secret_key = get_credentials()

    if not api_key or not secret_key:
        return {
            "configured": False,
            "api_key_preview": None,
            "message": "API 未配置。请编辑 config.json 填入 api_key 和 secret_key"
        }

    # 显示 key 预览（前5后4）
    if len(api_key) > 9:
        preview = f"{api_key[:5]}...{api_key[-4:]}"
    else:
        preview = "***"

    return {
        "configured": True,
        "api_key_preview": preview,
        "message": f"API 已配置 (Key: {preview})"
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="币安 API 工具")
    parser.add_argument("--check", action="store_true", help="检查 API 配置")
    parser.add_argument("--balance", action="store_true", help="查询余额")
    parser.add_argument("--positions", action="store_true", help="查询持仓")
    args = parser.parse_args()

    if args.check:
        status = check_api_config()
        print(status["message"])

    elif args.balance:
        balances = get_spot_balance()
        if "error" in balances:
            print(f"错误: {balances['error']}")
        else:
            print("现货余额:")
            for coin, bal in balances.items():
                if bal["free"] > 0 or bal["locked"] > 0:
                    print(f"  {coin}: {bal['free']:.8f} (可用) + {bal['locked']:.8f} (锁定)")

    elif args.positions:
        positions = get_dci_positions()
        if not positions:
            print("无持仓")
        else:
            print(f"持仓数量: {len(positions)}")
            for p in positions[:5]:
                print(f"  {p.get('optionType')} {p.get('exercisedCoin')} @ {p.get('strikePrice')}")

    else:
        parser.print_help()
