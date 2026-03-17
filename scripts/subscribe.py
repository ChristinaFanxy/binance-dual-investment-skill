#!/usr/bin/env python3
"""
申购执行与记录保存
真实申购模式，需用户输入 CONFIRM 确认
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from binance_api import subscribe_dci, check_api_config

SKILL_DIR = Path(__file__).parent.parent
SUBSCRIPTIONS_FILE = SKILL_DIR / "data" / "subscriptions.json"
POSITIONS_SCRIPT = SKILL_DIR / "scripts" / "positions.py"


def load_subscriptions() -> dict:
    """加载申购记录"""
    if not SUBSCRIPTIONS_FILE.exists():
        return {"subscriptions": []}

    with open(SUBSCRIPTIONS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_subscriptions(data: dict):
    """保存申购记录"""
    SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SUBSCRIPTIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def create_subscription_record(
    product: dict,
    invest_amount: float,
    invest_coin: str
) -> dict:
    """
    创建申购记录

    Args:
        product: 产品信息 (来自 calc_score 推荐)
        invest_amount: 投资金额
        invest_coin: 投资币种

    Returns:
        申购记录 dict
    """
    return {
        "id": str(uuid.uuid4()),
        "product_id": str(product.get("id", "")),
        "order_id": str(product.get("orderId", "")),
        "option_type": product.get("optionType"),
        "invest_coin": invest_coin,
        "invest_amount": invest_amount,
        "exercised_coin": product.get("exercisedCoin"),
        "strike_price": product.get("strikePrice"),
        "apr": product.get("apr"),
        "duration": product.get("duration"),
        "subscribe_time": datetime.now(timezone.utc).isoformat(),
        "settle_date": product.get("settleDate"),
        "status": "pending",  # pending -> active -> settled
        "result": None  # exercised / not_exercised
    }


def execute_subscription(
    product: dict,
    invest_amount: float,
    invest_coin: str,
    confirmed: bool = False
) -> dict:
    """
    执行申购

    Args:
        product: 产品信息
        invest_amount: 投资金额
        invest_coin: 投资币种
        confirmed: 是否已确认

    Returns:
        {
            "success": bool,
            "record": dict or None,
            "error": str or None,
            "needs_confirm": bool
        }
    """
    # 检查 API 配置
    config_status = check_api_config()
    if not config_status["configured"]:
        return {
            "success": False,
            "record": None,
            "error": config_status["message"],
            "needs_confirm": False
        }

    # 需要确认
    if not confirmed:
        return {
            "success": False,
            "record": None,
            "error": None,
            "needs_confirm": True
        }

    # 创建记录
    record = create_subscription_record(product, invest_amount, invest_coin)

    # 调用 API 申购
    result = subscribe_dci(
        product_id=record["product_id"],
        order_id=record["order_id"],
        amount=invest_amount
    )

    if "error" in result:
        record["status"] = "failed"
        record["error"] = result["error"]
        # 保存失败记录
        data = load_subscriptions()
        data["subscriptions"].append(record)
        save_subscriptions(data)

        return {
            "success": False,
            "record": record,
            "error": result["error"],
            "needs_confirm": False
        }

    # 申购成功
    record["status"] = "active"
    record["api_response"] = result

    # 保存记录
    data = load_subscriptions()
    data["subscriptions"].append(record)
    save_subscriptions(data)

    return {
        "success": True,
        "record": record,
        "error": None,
        "needs_confirm": False
    }


def format_subscription_preview(product: dict, invest_amount: float, invest_coin: str) -> str:
    """格式化申购预览"""
    opt_type = product.get("optionType")
    mode_name = "低买" if opt_type == "PUT" else "高卖"
    exercised_coin = product.get("exercisedCoin")
    strike = product.get("strikePrice", 0)
    apr = product.get("apr", 0)
    duration = product.get("duration", 0)

    # 格式化金额
    if invest_coin in ["USDT", "USDC"]:
        amount_str = f"{invest_amount:,.2f} {invest_coin}"
    elif invest_coin == "BTC":
        amount_str = f"{invest_amount:.6f} {invest_coin}"
    else:
        amount_str = f"{invest_amount:.4f} {invest_coin}"

    lines = [
        "━━ 申购确认 ━━",
        f"模式: {mode_name} ({opt_type})",
        f"标的: {exercised_coin}",
        f"行权价: ${strike:,.0f}",
        f"期限: {duration} 天",
        f"APR: {apr:.2f}%",
        f"投入: {amount_str}",
        "",
        "输入 CONFIRM 确认申购，其他任意键取消"
    ]

    return "\n".join(lines)


def format_subscription_result(record: dict) -> str:
    """格式化申购结果"""
    if record["status"] == "active":
        settle_dt = datetime.fromtimestamp(record['settle_date']/1000, tz=timezone.utc)
        lines = [
            "✅ 申购成功",
            f"记录 ID: {record['id'][:8]}...",
            f"产品: {record['option_type']} {record['exercised_coin']} @ ${record['strike_price']:,.0f}",
            f"金额: {record['invest_amount']} {record['invest_coin']}",
            f"到期: {settle_dt.strftime('%Y-%m-%d %H:%M')} UTC",
            "",
            "━━ 自动结算检查（OpenClaw）━━",
            "到期后 1 小时将自动检查结算，运行以下命令启用：",
            "",
            generate_settlement_check_command(record)
        ]
    else:
        lines = [
            "❌ 申购失败",
            f"错误: {record.get('error', '未知错误')}"
        ]

    return "\n".join(lines)


def get_active_subscriptions() -> list:
    """获取活跃的申购记录"""
    data = load_subscriptions()
    return [s for s in data["subscriptions"] if s["status"] == "active"]


def get_pending_settlements() -> list:
    """获取待结算的申购（到期日已过但未结算）"""
    data = load_subscriptions()
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    pending = []
    for s in data["subscriptions"]:
        if s["status"] == "active" and s["settle_date"] <= now_ms:
            pending.append(s)

    return pending


def generate_settlement_check_command(record: dict) -> str:
    """
    生成结算检查的 OpenClaw cron 命令
    到期时间 + 1 小时后执行检查

    Args:
        record: 申购记录

    Returns:
        OpenClaw cron 命令字符串
    """
    settle_ms = record["settle_date"]
    check_time_ms = settle_ms + 3600 * 1000  # +1 小时
    check_time = datetime.fromtimestamp(check_time_ms / 1000, tz=timezone.utc)
    check_time_iso = check_time.isoformat().replace("+00:00", "Z")

    record_id_short = record["id"][:8]

    cmd = f'''openclaw cron add \\
  --name "DCI结算检查-{record_id_short}" \\
  --at "{check_time_iso}" \\
  --session isolated \\
  --message "运行结算检查: python3 {POSITIONS_SCRIPT} --check --json --with-recommendations" \\
  --announce'''

    return cmd


def update_subscription_status(record_id: str, status: str, result: Optional[str] = None):
    """更新申购状态"""
    data = load_subscriptions()

    for s in data["subscriptions"]:
        if s["id"] == record_id:
            s["status"] = status
            if result:
                s["result"] = result
            s["updated_at"] = datetime.now(timezone.utc).isoformat()
            break

    save_subscriptions(data)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="申购管理")
    parser.add_argument("--list", action="store_true", help="列出所有申购记录")
    parser.add_argument("--active", action="store_true", help="列出活跃申购")
    parser.add_argument("--pending", action="store_true", help="列出待结算申购")
    args = parser.parse_args()

    if args.list:
        data = load_subscriptions()
        subs = data["subscriptions"]
        if not subs:
            print("无申购记录")
        else:
            print(f"共 {len(subs)} 条记录:")
            for s in subs[-10:]:  # 最近 10 条
                print(f"  [{s['status']}] {s['option_type']} {s['exercised_coin']} @ ${s['strike_price']:,.0f} - {s['invest_amount']} {s['invest_coin']}")

    elif args.active:
        active = get_active_subscriptions()
        if not active:
            print("无活跃申购")
        else:
            print(f"活跃申购 ({len(active)}):")
            for s in active:
                settle_dt = datetime.fromtimestamp(s['settle_date']/1000, tz=timezone.utc)
                print(f"  {s['option_type']} {s['exercised_coin']} @ ${s['strike_price']:,.0f} | 到期: {settle_dt.strftime('%m-%d %H:%M')} UTC")

    elif args.pending:
        pending = get_pending_settlements()
        if not pending:
            print("无待结算申购")
        else:
            print(f"待结算 ({len(pending)}):")
            for s in pending:
                print(f"  {s['id'][:8]}... {s['option_type']} {s['exercised_coin']} @ ${s['strike_price']:,.0f}")

    else:
        parser.print_help()
