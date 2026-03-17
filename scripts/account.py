#!/usr/bin/env python3
"""
账户扫描与资金解析
支持多种输入格式：1000 USDT、all USDT、50% BTC、1000 USDT + 0.5 ETH
"""

import re
import json
from pathlib import Path
from typing import Optional

from binance_api import get_spot_balance, get_all_balances, check_api_config, SUPPORTED_COINS

SKILL_DIR = Path(__file__).parent.parent


def scan_account() -> dict:
    """
    扫描账户余额（现货 + 资金账户）

    Returns:
        {
            "success": bool,
            "balances": {coin: {"free": float, "locked": float, "spot": float, "funding": float}},
            "error": str or None
        }
    """
    # 检查 API 配置
    config_status = check_api_config()
    if not config_status["configured"]:
        return {
            "success": False,
            "balances": {},
            "error": config_status["message"]
        }

    # 获取所有账户余额
    balances = get_all_balances(SUPPORTED_COINS)

    if "error" in balances:
        return {
            "success": False,
            "balances": {},
            "error": balances["error"]
        }

    return {
        "success": True,
        "balances": balances,
        "error": None
    }


def format_balance_display(balances: dict) -> str:
    """格式化余额显示"""
    lines = ["账户余额:"]

    for coin in SUPPORTED_COINS:
        bal = balances.get(coin, {"free": 0, "locked": 0, "spot": 0, "funding": 0})
        free = bal.get("free", 0)
        locked = bal.get("locked", 0)
        spot = bal.get("spot", 0)
        funding = bal.get("funding", 0)

        if free > 0 or locked > 0:
            # 根据币种选择精度
            if coin in ["USDT", "USDC"]:
                fmt = f"{free:,.2f}"
            elif coin == "BTC":
                fmt = f"{free:.6f}"
            else:  # ETH
                fmt = f"{free:.4f}"

            line = f"  {coin}: {fmt}"

            # 显示来源明细
            sources = []
            if spot > 0:
                sources.append(f"现货 {spot:.4f}")
            if funding > 0:
                sources.append(f"资金 {funding:.4f}")
            if sources:
                line += f" ({', '.join(sources)})"

            if locked > 0:
                line += f" [+{locked:.4f} 锁定]"
            lines.append(line)

    if len(lines) == 1:
        lines.append("  (无余额)")

    return "\n".join(lines)


def parse_fund_input(input_str: str, balances: dict) -> dict:
    """
    解析资金输入

    支持格式:
    - "1000 USDT"
    - "1000 USDT + 0.5 ETH + 0.3 BTC"
    - "all USDT"
    - "50% BTC"
    - "all"  (所有可用余额)

    Args:
        input_str: 用户输入
        balances: 当前余额 {coin: {"free": float, "locked": float}}

    Returns:
        {
            "success": bool,
            "funds": {coin: amount},  # 解析后的投资金额
            "error": str or None
        }
    """
    input_str = input_str.strip().upper()
    funds = {}

    # 特殊情况: "ALL" 表示所有可用余额
    if input_str == "ALL":
        for coin in SUPPORTED_COINS:
            free = balances.get(coin, {}).get("free", 0)
            if free > 0:
                funds[coin] = free
        if not funds:
            return {"success": False, "funds": {}, "error": "无可用余额"}
        return {"success": True, "funds": funds, "error": None}

    # 分割多个资金项 (用 + 分隔)
    parts = [p.strip() for p in input_str.split("+")]

    for part in parts:
        result = _parse_single_fund(part, balances)
        if not result["success"]:
            return result

        coin = result["coin"]
        amount = result["amount"]

        # 累加同币种
        funds[coin] = funds.get(coin, 0) + amount

    # 验证总额不超过余额
    for coin, amount in funds.items():
        available = balances.get(coin, {}).get("free", 0)
        if amount > available:
            return {
                "success": False,
                "funds": {},
                "error": f"{coin} 余额不足: 需要 {amount:.4f}，可用 {available:.4f}"
            }

    return {"success": True, "funds": funds, "error": None}


def _parse_single_fund(part: str, balances: dict) -> dict:
    """解析单个资金项"""
    part = part.strip()

    # 格式: "ALL COIN" (如 "ALL USDT")
    match = re.match(r"^ALL\s+(\w+)$", part)
    if match:
        coin = match.group(1)
        if coin not in SUPPORTED_COINS:
            return {"success": False, "error": f"不支持的币种: {coin}"}
        amount = balances.get(coin, {}).get("free", 0)
        if amount <= 0:
            return {"success": False, "error": f"{coin} 无可用余额"}
        return {"success": True, "coin": coin, "amount": amount}

    # 格式: "50% COIN" (如 "50% BTC")
    match = re.match(r"^(\d+(?:\.\d+)?)\s*%\s+(\w+)$", part)
    if match:
        percent = float(match.group(1))
        coin = match.group(2)
        if coin not in SUPPORTED_COINS:
            return {"success": False, "error": f"不支持的币种: {coin}"}
        if percent <= 0 or percent > 100:
            return {"success": False, "error": f"百分比无效: {percent}%"}
        available = balances.get(coin, {}).get("free", 0)
        amount = available * percent / 100
        if amount <= 0:
            return {"success": False, "error": f"{coin} 无可用余额"}
        return {"success": True, "coin": coin, "amount": amount}

    # 格式: "1000 COIN" 或 "0.5 COIN" (如 "1000 USDT", "0.5 ETH")
    match = re.match(r"^(\d+(?:\.\d+)?)\s+(\w+)$", part)
    if match:
        amount = float(match.group(1))
        coin = match.group(2)
        if coin not in SUPPORTED_COINS:
            return {"success": False, "error": f"不支持的币种: {coin}"}
        if amount <= 0:
            return {"success": False, "error": f"金额无效: {amount}"}
        return {"success": True, "coin": coin, "amount": amount}

    return {"success": False, "error": f"无法解析: {part}"}


def get_invest_mode(coin: str) -> str:
    """
    根据投资币种确定交易模式

    USDT/USDC -> PUT (低买)
    BTC/ETH -> CALL (高卖)
    """
    if coin in ["USDT", "USDC"]:
        return "PUT"
    else:
        return "CALL"


def format_funds_summary(funds: dict) -> str:
    """格式化资金摘要"""
    parts = []
    for coin, amount in funds.items():
        if coin in ["USDT", "USDC"]:
            parts.append(f"{amount:,.2f} {coin}")
        elif coin == "BTC":
            parts.append(f"{amount:.6f} {coin}")
        else:
            parts.append(f"{amount:.4f} {coin}")
    return " + ".join(parts)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="账户扫描与资金解析")
    parser.add_argument("--scan", action="store_true", help="扫描账户余额")
    parser.add_argument("--parse", type=str, help="解析资金输入")
    args = parser.parse_args()

    if args.scan:
        result = scan_account()
        if result["success"]:
            print(format_balance_display(result["balances"]))
        else:
            print(f"错误: {result['error']}")

    elif args.parse:
        # 先扫描余额
        scan_result = scan_account()
        if not scan_result["success"]:
            print(f"错误: {scan_result['error']}")
        else:
            # 解析输入
            parse_result = parse_fund_input(args.parse, scan_result["balances"])
            if parse_result["success"]:
                print(f"解析成功: {format_funds_summary(parse_result['funds'])}")
                for coin, amount in parse_result["funds"].items():
                    mode = get_invest_mode(coin)
                    print(f"  {coin} -> {mode} 模式")
            else:
                print(f"解析失败: {parse_result['error']}")

    else:
        parser.print_help()
