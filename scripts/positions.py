#!/usr/bin/env python3
"""
持仓查询与行权检查
判断 PUT/CALL 是否被行权，输出结果并建议复投方向
支持 JSON 输出供 OpenClaw 解析
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from binance_api import get_dci_positions, get_spot_balance, check_api_config

SKILL_DIR = Path(__file__).parent.parent
SUBSCRIPTIONS_FILE = SKILL_DIR / "data" / "subscriptions.json"
MARKET_DATA_FILE = SKILL_DIR / "data" / "market_data.json"


def load_subscriptions() -> dict:
    """加载本地申购记录"""
    if not SUBSCRIPTIONS_FILE.exists():
        return {"subscriptions": []}
    with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_subscriptions(data: dict):
    """保存申购记录"""
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_api_positions() -> dict:
    """
    获取 API 持仓

    Returns:
        {
            "success": bool,
            "positions": list,
            "error": str or None
        }
    """
    config_status = check_api_config()
    if not config_status["configured"]:
        return {
            "success": False,
            "positions": [],
            "error": config_status["message"]
        }

    positions = get_dci_positions()
    return {
        "success": True,
        "positions": positions,
        "error": None
    }


def check_exercise_result(subscription: dict, spot_price: float) -> dict:
    """
    判断行权结果并计算收益

    PUT (低买):
    - 行权: 现价 <= 行权价 → 用 USDT 买入 BTC/ETH
    - 未行权: 现价 > 行权价 → 返还 USDT + 保费

    CALL (高卖):
    - 行权: 现价 >= 行权价 → 卖出 BTC/ETH 换 USDT
    - 未行权: 现价 < 行权价 → 返还 BTC/ETH + 保费

    Args:
        subscription: 申购记录
        spot_price: 结算时现价

    Returns:
        {
            "exercised": bool,
            "result_coin": str,  # 结算后持有的币种
            "description": str,
            "next_mode": str,  # 建议的下一步模式
            "profit": {
                "premium_earned": float,
                "premium_coin": str,
                "pnl": float,
                "pnl_coin": str,
                "total_return_pct": float
            },
            "position_change": {
                "from": {"coin": str, "amount": float},
                "to": {"coin": str, "amount": float}
            }
        }
    """
    opt_type = subscription["option_type"]
    strike = subscription["strike_price"]
    invest_coin = subscription["invest_coin"]
    invest_amount = subscription["invest_amount"]
    exercised_coin = subscription["exercised_coin"]
    apr = subscription["apr"]  # 百分比形式，如 211.21
    duration = subscription["duration"]

    # 计算保费收入
    premium = invest_amount * (apr / 100) * duration / 365

    if opt_type == "PUT":
        # PUT: 投入 USDT，标的 BTC/ETH
        if spot_price <= strike:
            # 行权: USDT -> BTC/ETH
            coins_received = invest_amount / strike
            market_value = coins_received * spot_price
            # 盈亏 = 市值 - 本金 + 保费 (以 USDT 计)
            pnl = market_value - invest_amount + premium
            total_return_pct = (pnl / invest_amount) * 100

            return {
                "exercised": True,
                "result_coin": exercised_coin,
                "description": f"行权: 以 ${strike:,.0f} 买入 {exercised_coin}",
                "next_mode": "CALL",  # 接下来高卖
                "profit": {
                    "premium_earned": round(premium, 2),
                    "premium_coin": invest_coin,
                    "pnl": round(pnl, 2),
                    "pnl_coin": invest_coin,
                    "total_return_pct": round(total_return_pct, 2)
                },
                "position_change": {
                    "from": {"coin": invest_coin, "amount": invest_amount},
                    "to": {"coin": exercised_coin, "amount": round(coins_received, 8)}
                }
            }
        else:
            # 未行权: 返还 USDT + 保费
            total_return_pct = (premium / invest_amount) * 100

            return {
                "exercised": False,
                "result_coin": invest_coin,
                "description": f"未行权: 返还 {invest_coin} + 保费",
                "next_mode": "PUT",  # 继续低买
                "profit": {
                    "premium_earned": round(premium, 2),
                    "premium_coin": invest_coin,
                    "pnl": round(premium, 2),  # 纯保费收益
                    "pnl_coin": invest_coin,
                    "total_return_pct": round(total_return_pct, 2)
                },
                "position_change": {
                    "from": {"coin": invest_coin, "amount": invest_amount},
                    "to": {"coin": invest_coin, "amount": round(invest_amount + premium, 2)}
                }
            }

    else:  # CALL
        # CALL: 投入 BTC/ETH，标的 USDT
        # 保费以币本位计
        premium_in_coin = premium  # 这里 premium 已经是币本位

        if spot_price >= strike:
            # 行权: BTC/ETH -> USDT
            usdt_received = invest_amount * strike
            # 机会成本: 如果不卖，市值是 invest_amount * spot_price
            opportunity_cost = invest_amount * spot_price
            # 盈亏 = 获得 USDT - 机会成本 + 保费市值
            premium_value = premium_in_coin * spot_price
            pnl = usdt_received - opportunity_cost + premium_value
            total_return_pct = (pnl / opportunity_cost) * 100

            return {
                "exercised": True,
                "result_coin": "USDT",
                "description": f"行权: 以 ${strike:,.0f} 卖出 {invest_coin}",
                "next_mode": "PUT",  # 接下来低买
                "profit": {
                    "premium_earned": round(premium_in_coin, 8),
                    "premium_coin": invest_coin,
                    "pnl": round(pnl, 2),
                    "pnl_coin": "USDT",
                    "total_return_pct": round(total_return_pct, 2)
                },
                "position_change": {
                    "from": {"coin": invest_coin, "amount": invest_amount},
                    "to": {"coin": "USDT", "amount": round(usdt_received + premium_value, 2)}
                }
            }
        else:
            # 未行权: 返还 BTC/ETH + 保费
            total_return_pct = (premium_in_coin / invest_amount) * 100

            return {
                "exercised": False,
                "result_coin": invest_coin,
                "description": f"未行权: 返还 {invest_coin} + 保费",
                "next_mode": "CALL",  # 继续高卖
                "profit": {
                    "premium_earned": round(premium_in_coin, 8),
                    "premium_coin": invest_coin,
                    "pnl": round(premium_in_coin, 8),  # 纯保费收益（币本位）
                    "pnl_coin": invest_coin,
                    "total_return_pct": round(total_return_pct, 2)
                },
                "position_change": {
                    "from": {"coin": invest_coin, "amount": invest_amount},
                    "to": {"coin": invest_coin, "amount": round(invest_amount + premium_in_coin, 8)}
                }
            }


def check_pending_settlements(spot_prices: dict) -> list:
    """
    检查待结算的申购

    Args:
        spot_prices: {"BTC": price, "ETH": price}

    Returns:
        结算结果列表
    """
    data = load_subscriptions()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    results = []

    for sub in data["subscriptions"]:
        # 只检查活跃且已到期的
        if sub["status"] != "active":
            continue
        if sub["settle_date"] > now_ms:
            continue

        # 获取现价
        coin = sub["exercised_coin"]
        spot = spot_prices.get(coin)

        if not spot:
            results.append({
                "subscription": sub,
                "error": f"无法获取 {coin} 现价"
            })
            continue

        # 判断行权结果
        exercise_result = check_exercise_result(sub, spot)

        # 更新记录
        sub["status"] = "settled"
        sub["result"] = "exercised" if exercise_result["exercised"] else "not_exercised"
        sub["settle_price"] = spot
        sub["settled_at"] = datetime.now(timezone.utc).isoformat()

        results.append({
            "subscription": sub,
            "exercise_result": exercise_result,
            "spot_price": spot
        })

    # 保存更新
    save_subscriptions(data)

    return results


def format_settlement_result(result: dict) -> str:
    """格式化结算结果"""
    if "error" in result:
        sub = result["subscription"]
        return f"❌ {sub['option_type']} {sub['exercised_coin']} @ ${sub['strike_price']:,.0f}: {result['error']}"

    sub = result["subscription"]
    ex = result["exercise_result"]
    spot = result["spot_price"]
    profit = ex.get("profit", {})

    icon = "🔄" if ex["exercised"] else "✅"
    lines = [
        f"{icon} {sub['option_type']} {sub['exercised_coin']} @ ${sub['strike_price']:,.0f}",
        f"   结算价: ${spot:,.0f}",
        f"   {ex['description']}",
    ]

    # 添加收益信息
    if profit:
        premium = profit.get("premium_earned", 0)
        premium_coin = profit.get("premium_coin", "")
        pnl = profit.get("pnl", 0)
        pnl_coin = profit.get("pnl_coin", "")
        return_pct = profit.get("total_return_pct", 0)

        if premium_coin in ["USDT", "USDC"]:
            lines.append(f"   保费: {premium:,.2f} {premium_coin}")
        else:
            lines.append(f"   保费: {premium:.8f} {premium_coin}")

        if pnl_coin in ["USDT", "USDC"]:
            pnl_str = f"{pnl:+,.2f} {pnl_coin}"
        else:
            pnl_str = f"{pnl:+.8f} {pnl_coin}"

        pnl_icon = "📈" if pnl >= 0 else "📉"
        lines.append(f"   {pnl_icon} 盈亏: {pnl_str} ({return_pct:+.2f}%)")

    lines.append(f"   建议: 切换到 {ex['next_mode']} 模式")

    return "\n".join(lines)


def get_next_recommendations(settlement_results: list) -> list:
    """
    根据结算结果获取下轮推荐

    调用 calc_score.py 获取推荐产品

    Args:
        settlement_results: 结算结果列表

    Returns:
        推荐产品列表
    """
    recommendations = []

    for result in settlement_results:
        if "error" in result:
            continue

        ex = result["exercise_result"]
        sub = result["subscription"]
        position_change = ex.get("position_change", {})
        to_position = position_change.get("to", {})

        # 确定下轮投资参数
        next_mode = ex["next_mode"]
        result_coin = to_position.get("coin", ex["result_coin"])
        result_amount = to_position.get("amount", sub["invest_amount"])

        # 构建 funds 参数
        funds_str = f"{result_amount} {result_coin}"

        # 调用 calc_score.py
        calc_script = SKILL_DIR / "scripts" / "calc_score.py"
        try:
            cmd = [sys.executable, str(calc_script), "--funds", funds_str, "--json"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if proc.returncode == 0 and proc.stdout.strip():
                rec_data = json.loads(proc.stdout)
                # 提取推荐
                for coin_key, coin_data in rec_data.items():
                    recs = coin_data.get("recommendations", [])
                    for rec in recs[:2]:  # 取前2个
                        recommendations.append({
                            "mode": coin_data.get("mode"),
                            "coin": rec.get("exercisedCoin"),
                            "strike": rec.get("strikePrice"),
                            "apr": rec.get("apr"),
                            "duration": rec.get("duration"),
                            "score": rec.get("score"),
                            "delta": rec.get("delta"),
                            "from_settlement_id": sub.get("id"),
                        })
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

    return recommendations


def build_settlement_json(results: list, spot_prices: dict, with_recommendations: bool = False) -> dict:
    """
    构建结算 JSON 输出（供 OpenClaw 解析）

    Args:
        results: 结算结果列表
        spot_prices: 现价字典
        with_recommendations: 是否包含下轮推荐

    Returns:
        结构化 JSON 数据
    """
    settlements = []

    for result in results:
        sub = result["subscription"]

        if "error" in result:
            settlements.append({
                "id": sub.get("id"),
                "error": result["error"]
            })
            continue

        ex = result["exercise_result"]
        spot = result["spot_price"]
        profit = ex.get("profit", {})
        position_change = ex.get("position_change", {})

        settlement = {
            "id": sub.get("id"),
            "option_type": sub["option_type"],
            "exercised_coin": sub["exercised_coin"],
            "strike_price": sub["strike_price"],
            "settle_price": spot,
            "exercised": ex["exercised"],
            "profit": profit,
            "position_change": position_change,
            "wheel_suggestion": {
                "next_mode": ex["next_mode"],
                "reason": _get_wheel_reason(ex)
            }
        }
        settlements.append(settlement)

    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "settlements": settlements,
    }

    if with_recommendations:
        output["next_recommendations"] = get_next_recommendations(results)

    return output


def _get_wheel_reason(exercise_result: dict) -> str:
    """生成车轮策略建议原因"""
    exercised = exercise_result["exercised"]
    next_mode = exercise_result["next_mode"]

    if next_mode == "CALL":
        if exercised:
            return "低买行权成功，建议高卖赚取保费"
        else:
            return "低买未行权，继续低买积累保费"
    else:  # PUT
        if exercised:
            return "高卖行权成功，建议低买接回筹码"
        else:
            return "高卖未行权，继续高卖积累保费"


def get_active_positions_summary() -> dict:
    """
    获取活跃持仓摘要

    Returns:
        {
            "total_count": int,
            "by_type": {"PUT": count, "CALL": count},
            "by_coin": {"BTC": count, "ETH": count},
            "next_settle": datetime or None
        }
    """
    data = load_subscriptions()
    active = [s for s in data["subscriptions"] if s["status"] == "active"]

    if not active:
        return {
            "total_count": 0,
            "by_type": {},
            "by_coin": {},
            "next_settle": None
        }

    by_type = {}
    by_coin = {}
    next_settle_ms = None

    for s in active:
        opt_type = s["option_type"]
        coin = s["exercised_coin"]

        by_type[opt_type] = by_type.get(opt_type, 0) + 1
        by_coin[coin] = by_coin.get(coin, 0) + 1

        if next_settle_ms is None or s["settle_date"] < next_settle_ms:
            next_settle_ms = s["settle_date"]

    next_settle = None
    if next_settle_ms:
        next_settle = datetime.fromtimestamp(next_settle_ms / 1000, tz=timezone.utc)

    return {
        "total_count": len(active),
        "by_type": by_type,
        "by_coin": by_coin,
        "next_settle": next_settle
    }


def format_positions_summary(summary: dict) -> str:
    """格式化持仓摘要"""
    if summary["total_count"] == 0:
        return "无活跃持仓"

    lines = [f"活跃持仓: {summary['total_count']} 笔"]

    if summary["by_type"]:
        type_str = ", ".join(f"{k}: {v}" for k, v in summary["by_type"].items())
        lines.append(f"  类型: {type_str}")

    if summary["by_coin"]:
        coin_str = ", ".join(f"{k}: {v}" for k, v in summary["by_coin"].items())
        lines.append(f"  标的: {coin_str}")

    if summary["next_settle"]:
        lines.append(f"  最近到期: {summary['next_settle'].strftime('%Y-%m-%d %H:%M')} UTC")

    return "\n".join(lines)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="持仓查询与行权检查")
    parser.add_argument("--check", action="store_true", help="检查待结算持仓")
    parser.add_argument("--summary", action="store_true", help="显示持仓摘要")
    parser.add_argument("--api", action="store_true", help="从 API 获取持仓")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式（供 OpenClaw 解析）")
    parser.add_argument("--with-recommendations", action="store_true", help="包含下轮推荐")
    args = parser.parse_args()

    if args.check:
        # 需要现价来判断行权
        if MARKET_DATA_FILE.exists():
            with open(MARKET_DATA_FILE) as f:
                market_data = json.load(f)
            spot_prices = market_data.get("spot_prices", {})
        else:
            if args.json:
                print(json.dumps({"error": "无市场数据，请先运行 fetch_data.py"}))
            else:
                print("错误: 无市场数据，请先运行 fetch_data.py")
            exit(1)

        results = check_pending_settlements(spot_prices)

        if args.json:
            # JSON 输出模式
            output = build_settlement_json(
                results,
                spot_prices,
                with_recommendations=args.with_recommendations
            )
            print(json.dumps(output, indent=2, ensure_ascii=False))
        else:
            # 人类可读输出
            if not results:
                print("无待结算持仓")
            else:
                print(f"结算检查 ({len(results)} 笔):\n")
                for r in results:
                    print(format_settlement_result(r))
                    print()

                # 如果需要推荐
                if args.with_recommendations:
                    recs = get_next_recommendations(results)
                    if recs:
                        print("━━ 下轮推荐 ━━")
                        for rec in recs[:3]:
                            mode_name = "低买" if rec["mode"] == "PUT" else "高卖"
                            print(
                                f"  {mode_name} {rec['coin']} @ ${rec['strike']:,.0f} | "
                                f"{rec['duration']}天 | APR {rec['apr']:.1f}% | 得分 {rec['score']:.1f}"
                            )

    elif args.summary:
        summary = get_active_positions_summary()
        print(format_positions_summary(summary))

    elif args.api:
        result = get_api_positions()
        if not result["success"]:
            print(f"错误: {result['error']}")
        elif not result["positions"]:
            print("API 无持仓")
        else:
            print(f"API 持仓 ({len(result['positions'])}):")
            for p in result["positions"][:10]:
                print(f"  {p.get('optionType')} {p.get('exercisedCoin')} @ ${p.get('strikePrice', 0):,.0f}")

    else:
        parser.print_help()
