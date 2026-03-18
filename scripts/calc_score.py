#!/usr/bin/env python3
"""
Dual Investment 评分计算脚本
读取市场数据，匹配 Delta，计算评分并输出推荐
支持多币种投资金额推荐
"""

import json
import argparse
import re
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

SKILL_DIR = Path(__file__).parent.parent
DATA_FILE = SKILL_DIR / "data" / "market_data.json"

# 投资币种到模式的映射
INVEST_COIN_MODE = {
    "USDT": "PUT",
    "USDC": "PUT",
    "BTC": "CALL",
    "ETH": "CALL",
}


def norm_cdf(x: float) -> float:
    """标准正态分布 CDF（近似）"""
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
    d1 = (math.log(S / K) + (r + sigma ** 2 / 2) * T) / (math.sqrt(T) * sigma)
    if option_type == "C":
        return norm_cdf(d1)
    else:
        return norm_cdf(d1) - 1


def load_market_data() -> dict:
    """加载市场数据"""
    if not DATA_FILE.exists():
        print(f"错误: 数据文件不存在 {DATA_FILE}")
        print("请先运行 fetch_data.py 获取数据")
        return {}

    with open(DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def parse_deribit_instrument(name: str) -> dict:
    """解析 Deribit 合约名称
    例如: BTC-17MAR26-80000-P
    """
    pattern = r"^(\w+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+)-([PC])$"
    match = re.match(pattern, name)
    if not match:
        return {}

    currency, day, month, year, strike, opt_type = match.groups()

    month_map = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }

    return {
        "currency": currency,
        "expiry_date": datetime(2000 + int(year), month_map[month], int(day)),
        "strike": float(strike),
        "option_type": "PUT" if opt_type == "P" else "CALL",
    }


def build_delta_index(deribit_deltas: dict) -> dict:
    """构建 Delta 索引，加速匹配查找

    索引结构: {(currency, option_type, strike): [(expiry_ms, delta, instrument), ...]}
    每个 key 下的列表按 expiry_ms 排序
    """
    index = {}
    for instrument, delta in deribit_deltas.items():
        parsed = parse_deribit_instrument(instrument)
        if not parsed:
            continue
        key = (parsed["currency"], parsed["option_type"], parsed["strike"])
        expiry_ms = int(parsed["expiry_date"].timestamp() * 1000)
        if key not in index:
            index[key] = []
        index[key].append((expiry_ms, delta, instrument))

    # 按到期时间排序
    for key in index:
        index[key].sort(key=lambda x: x[0])

    return index


def match_delta_indexed(
    product: dict,
    delta_index: dict,
    spot_prices: dict,
    dvol: dict
) -> float | None:
    """使用索引快速匹配 Delta（O(1) 查找 + O(k) 遍历）"""
    coin = product["exercisedCoin"]
    strike = product["strikePrice"]
    opt_type = product["optionType"]
    settle_ms = product["settleDate"]
    duration_days = product["duration"]

    # O(1) 索引查找
    key = (coin, opt_type, strike)
    candidates = delta_index.get(key, [])

    best_match = None
    best_diff = float("inf")

    # O(k) 遍历候选（通常 k=1-3）
    for expiry_ms, delta, instrument in candidates:
        diff_ratio = abs(expiry_ms - settle_ms) / (duration_days * 86400000)
        if diff_ratio > 0.5:
            continue
        if diff_ratio < best_diff:
            best_diff = diff_ratio
            best_match = delta

    # BS Delta fallback
    if best_match is None or best_match == 0.0:
        S = spot_prices.get(coin)
        coin_dvol = dvol.get(coin)
        if S and coin_dvol:
            current_ms = int(time.time() * 1000)
            T = (settle_ms - current_ms) / (365.25 * 24 * 3600 * 1000)
            sigma = coin_dvol / 100
            opt_char = "P" if opt_type == "PUT" else "C"
            best_match = bs_delta(S, strike, T, sigma, option_type=opt_char)

    return best_match


def get_delta_limit(dvol: float) -> float:
    """根据 DVOL 获取 Delta 上限"""
    if dvol > 70:
        return 0.15
    elif dvol >= 40:
        return 0.30
    else:
        return 0.35


def calculate_scores(
    products: list,
    deribit_deltas: dict,
    dvol: dict,
    spot_prices: dict,
    mode: str,
    cost_basis: float = None,
    target_coin: str = None,
    delta_index: dict = None
) -> list:
    """计算产品评分

    Args:
        products: 产品列表
        deribit_deltas: Deribit Delta 数据
        dvol: DVOL 数据
        spot_prices: 现价数据
        mode: PUT 或 CALL
        cost_basis: 成本价（CALL 模式用）
        target_coin: 目标标的币种（BTC/ETH），用于过滤
        delta_index: 预计算的 Delta 索引（可选，用于加速匹配）
    """
    results = []

    # 如果没有传入索引，构建一个
    if delta_index is None:
        delta_index = build_delta_index(deribit_deltas)

    for product in products:
        # 过滤条件
        if product["optionType"] != mode:
            continue
        if not product.get("canPurchase"):
            continue
        if not (1 <= product["duration"] <= 5):
            continue
        if product["apr"] < 3:  # APR 现在是百分比形式，3 = 3%
            continue

        # 目标币种过滤
        if target_coin and product["exercisedCoin"] != target_coin:
            continue

        # CALL 模式：行权价必须 >= 成本价
        if mode == "CALL" and cost_basis:
            if product["strikePrice"] < cost_basis:
                continue

        # 使用索引匹配 Delta
        delta = match_delta_indexed(product, delta_index, spot_prices, dvol)
        if delta is None:
            continue

        abs_delta = abs(delta)

        # Delta 过滤
        if abs_delta < 0.05:
            continue

        # DVOL 风控
        coin = product["exercisedCoin"]
        coin_dvol = dvol.get(coin, 50)
        delta_limit = get_delta_limit(coin_dvol)

        if abs_delta > delta_limit:
            continue

        # 计算评分
        score = product["apr"] / max(abs_delta, 0.01)

        results.append({
            **product,
            "delta": delta,
            "abs_delta": abs_delta,
            "score": score,
            "dvol": coin_dvol,
        })

    # 按评分降序排序
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def format_output(results: list, mode: str, spot_prices: dict, dvol: dict) -> str:
    """格式化输出"""
    if not results:
        return f"未找到符合条件的 {mode} 产品"

    lines = []
    lines.append(f"📊 双币投资推荐 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    coin = results[0]["exercisedCoin"]
    spot = spot_prices.get(coin, "N/A")
    coin_dvol = dvol.get(coin, "N/A")
    mode_name = "低买" if mode == "PUT" else "高卖"
    delta_limit = get_delta_limit(coin_dvol)

    lines.append(f"{coin} ${spot:,.0f} | DVOL {coin_dvol:.1f}% | 模式: {mode_name}")
    lines.append("")

    # 筛选条件说明
    lines.append("━━ 筛选条件 ━━")
    lines.append(f"  期限: 1-5 天")
    lines.append(f"  APR: ≥ 3%")
    lines.append(f"  Delta: 0.05 ~ {delta_limit:.2f} (根据 DVOL {coin_dvol:.0f}% 动态调整)")
    lines.append("")

    # 评分公式说明
    lines.append("━━ 评分公式 ━━")
    lines.append("  Score = APR / |Delta|")
    lines.append("  APR 越高、Delta 越低 → 得分越高")
    lines.append("")

    # Top 3 排名
    lines.append("━━ 排名 ━━")
    for i, rec in enumerate(results[:3], 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}[i]
        lines.append(
            f"  {medal} 第{i}名: {mode_name} ${rec['strikePrice']:,.0f} | {rec['duration']}天 | "
            f"APR {rec['apr']:.1f}% | Δ {rec['delta']:.3f} | 得分 {rec['score']:.1f}"
        )

    lines.append("")
    lines.append("被行权: 低买→接币切高卖 | 高卖→换U切低买")
    lines.append("DYOR。")

    return "\n".join(lines)


def get_recommendations_for_funds(
    funds: dict,
    products: list,
    deribit_deltas: dict,
    dvol: dict,
    spot_prices: dict,
    cost_basis: dict = None
) -> dict:
    """
    根据投资资金获取推荐

    Args:
        funds: {coin: amount} 投资金额
        products: 产品列表
        deribit_deltas: Deribit Delta 数据
        dvol: DVOL 数据
        spot_prices: 现价数据
        cost_basis: {coin: price} 各币种成本价（CALL 模式用）

    Returns:
        {
            coin: {
                "mode": "PUT" or "CALL",
                "amount": float,
                "recommendations": list,  # 推荐产品列表
            }
        }
    """
    cost_basis = cost_basis or {}
    results = {}

    # 预计算 Delta 索引（只构建一次）
    delta_index = build_delta_index(deribit_deltas)

    for coin, amount in funds.items():
        mode = INVEST_COIN_MODE.get(coin)
        if not mode:
            continue

        # 确定目标标的
        # PUT: USDT/USDC -> BTC 或 ETH
        # CALL: BTC -> BTC, ETH -> ETH
        if mode == "PUT":
            # 稳定币可以买 BTC 或 ETH，分别计算
            btc_recs = calculate_scores(
                products, deribit_deltas, dvol, spot_prices,
                mode="PUT", target_coin="BTC", delta_index=delta_index
            )
            eth_recs = calculate_scores(
                products, deribit_deltas, dvol, spot_prices,
                mode="PUT", target_coin="ETH", delta_index=delta_index
            )
            # 合并并按评分排序
            all_recs = btc_recs + eth_recs
            all_recs.sort(key=lambda x: x["score"], reverse=True)
            recommendations = all_recs[:5]
        else:
            # CALL: 只能卖对应币种
            recommendations = calculate_scores(
                products, deribit_deltas, dvol, spot_prices,
                mode="CALL",
                cost_basis=cost_basis.get(coin),
                target_coin=coin,
                delta_index=delta_index
            )[:5]

        results[coin] = {
            "mode": mode,
            "amount": amount,
            "recommendations": recommendations
        }

    return results


def format_multi_coin_output(
    recommendations: dict,
    spot_prices: dict,
    dvol: dict
) -> str:
    """格式化多币种推荐输出"""
    lines = []
    lines.append(f"📊 双币投资推荐 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # 筛选条件说明（只显示一次）
    lines.append("━━ 筛选条件 ━━")
    lines.append("  期限: 1-5 天")
    lines.append("  APR: ≥ 3%")
    lines.append("  Delta: 0.05 ~ 动态上限 (根据 DVOL 调整)")
    lines.append("    DVOL > 70% → Delta ≤ 0.15")
    lines.append("    DVOL 40-70% → Delta ≤ 0.30")
    lines.append("    DVOL < 40% → Delta ≤ 0.35")
    lines.append("")

    # 评分公式说明
    lines.append("━━ 评分公式 ━━")
    lines.append("  Score = APR / |Delta|")
    lines.append("  APR 越高、Delta 越低 → 得分越高")
    lines.append("")

    for coin, data in recommendations.items():
        mode = data["mode"]
        amount = data["amount"]
        recs = data["recommendations"]

        mode_name = "低买" if mode == "PUT" else "高卖"

        # 格式化金额
        if coin in ["USDT", "USDC"]:
            amount_str = f"{amount:,.2f} {coin}"
        elif coin == "BTC":
            amount_str = f"{amount:.6f} {coin}"
        else:
            amount_str = f"{amount:.4f} {coin}"

        lines.append(f"━━ {amount_str} → {mode_name} ━━")

        if not recs:
            lines.append("  无符合条件的产品")
            lines.append("")
            continue

        # 市场信息
        target_coin = recs[0]["exercisedCoin"]
        spot = spot_prices.get(target_coin, 0)
        coin_dvol = dvol.get(target_coin, 0)
        lines.append(f"  {target_coin} ${spot:,.0f} | DVOL {coin_dvol:.1f}%")
        lines.append("")

        # Top 3 排名
        for i, rec in enumerate(recs[:3], 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}[i]
            lines.append(
                f"  {medal} 第{i}名: {mode_name} ${rec['strikePrice']:,.0f} | {rec['duration']}天 | "
                f"APR {rec['apr']:.1f}% | Δ {rec['delta']:.3f} | 得分 {rec['score']:.1f}"
            )

        lines.append("")

    lines.append("被行权: 低买→接币切高卖 | 高卖→换U切低买")
    lines.append("DYOR。")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="计算双币投资产品评分")
    parser.add_argument("--mode", choices=["PUT", "CALL"], default="PUT", help="交易模式")
    parser.add_argument("--cost-basis", type=float, help="成本价（CALL 模式用）")
    parser.add_argument("--coin", type=str, help="目标标的币种 (BTC/ETH)")
    parser.add_argument("--funds", type=str, help="投资资金，如 '1000 USDT' 或 '1000 USDT + 0.5 ETH'")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    # 加载数据
    data = load_market_data()
    if not data:
        return

    # 多币种模式
    if args.funds:
        # 简单解析 funds 参数
        funds = {}
        parts = [p.strip().upper() for p in args.funds.split("+")]
        for part in parts:
            tokens = part.split()
            if len(tokens) == 2:
                amount, coin = float(tokens[0]), tokens[1]
                funds[coin] = funds.get(coin, 0) + amount

        recommendations = get_recommendations_for_funds(
            funds=funds,
            products=data.get("binance_products", []),
            deribit_deltas=data.get("deribit_deltas", {}),
            dvol=data.get("dvol", {}),
            spot_prices=data.get("spot_prices", {}),
        )

        if args.json:
            print(json.dumps(recommendations, indent=2, ensure_ascii=False, default=str))
        else:
            output = format_multi_coin_output(
                recommendations,
                data.get("spot_prices", {}),
                data.get("dvol", {}),
            )
            print(output)
        return

    # 单模式
    results = calculate_scores(
        products=data.get("binance_products", []),
        deribit_deltas=data.get("deribit_deltas", {}),
        dvol=data.get("dvol", {}),
        spot_prices=data.get("spot_prices", {}),
        mode=args.mode,
        cost_basis=args.cost_basis,
        target_coin=args.coin,
    )

    # 输出
    if args.json:
        print(json.dumps(results[:5], indent=2, ensure_ascii=False))
    else:
        output = format_output(
            results,
            args.mode,
            data.get("spot_prices", {}),
            data.get("dvol", {}),
        )
        print(output)


if __name__ == "__main__":
    main()
