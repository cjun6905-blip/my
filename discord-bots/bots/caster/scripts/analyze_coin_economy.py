# -*- coding: utf-8 -*-
"""
类脑币经济分析脚本
用于详细统计用户类脑币分布情况，为商品定价提供数据支持
"""

import os
import sys
import asyncio
import statistics
from datetime import datetime
from collections import Counter

# 将项目根目录添加到 sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

from src.chat.utils.database import chat_db_manager
from src.chat.config.shop_config import SHOP_ITEMS


def calculate_percentiles(data, percentiles):
    """计算指定百分位数"""
    sorted_data = sorted(data)
    n = len(sorted_data)
    results = {}
    for p in percentiles:
        index = int(n * p / 100)
        if index >= n:
            index = n - 1
        results[p] = sorted_data[index]
    return results


def calculate_gini_coefficient(data):
    """计算基尼系数（财富不平等程度）"""
    sorted_data = sorted(data)
    n = len(sorted_data)
    if n == 0:
        return 0

    cumulative_sum = 0
    for i, value in enumerate(sorted_data):
        cumulative_sum += (i + 1) * value

    sum_values = sum(sorted_data)
    if sum_values == 0:
        return 0

    gini = (2 * cumulative_sum) / (n * sum_values) - (n + 1) / n
    return max(0, min(1, gini))


def calculate_skewness(data):
    """计算偏度（数据分布的对称性）"""
    if len(data) < 3:
        return 0

    mean = statistics.mean(data)
    std = statistics.stdev(data)
    if std == 0:
        return 0

    skew = sum((x - mean) ** 3 for x in data) / (len(data) * std**3)
    return skew


def calculate_kurtosis(data):
    """计算峰度（数据分布的尖锐程度）"""
    if len(data) < 4:
        return 0

    mean = statistics.mean(data)
    std = statistics.stdev(data)
    if std == 0:
        return 0

    kurt = sum((x - mean) ** 4 for x in data) / (len(data) * std**4) - 3
    return kurt


async def analyze_shop_items():
    """分析商品价格分布"""
    print("\n--- 分析商品价格分布 ---")

    items_by_category = {}
    for item in SHOP_ITEMS:
        name, desc, price, category, target, effect_id = item
        if category not in items_by_category:
            items_by_category[category] = []
        items_by_category[category].append(
            {"name": name, "price": price, "description": desc}
        )

    # 统计价格分布
    all_prices = [
        item["price"] for category in items_by_category.values() for item in category
    ]

    analysis = {
        "total_items": len(SHOP_ITEMS),
        "categories": {},
        "price_distribution": {
            "min": min(all_prices) if all_prices else 0,
            "max": max(all_prices) if all_prices else 0,
            "mean": statistics.mean(all_prices) if all_prices else 0,
            "median": statistics.median(all_prices) if all_prices else 0,
            "free_items": len([p for p in all_prices if p == 0]),
            "price_ranges": Counter(
                "0"
                if p == 0
                else "1-10"
                if 1 <= p <= 10
                else "11-50"
                if 11 <= p <= 50
                else "51-100"
                if 51 <= p <= 100
                else "101-200"
                if 101 <= p <= 200
                else "200+"
                if p > 200
                else "unknown"
                for p in all_prices
            ),
        },
    }

    # 按分类统计
    for category, items in items_by_category.items():
        prices = [item["price"] for item in items]
        analysis["categories"][category] = {
            "count": len(items),
            "min_price": min(prices) if prices else 0,
            "max_price": max(prices) if prices else 0,
            "avg_price": statistics.mean(prices) if prices else 0,
            "items": items,
        }

    return analysis


async def analyze_user_balances():
    """分析用户余额分布"""
    print("\n--- 分析用户余额分布 ---")

    query = "SELECT user_id, balance FROM user_coins ORDER BY balance DESC"

    results = await chat_db_manager._execute(
        chat_db_manager._db_transaction, query, fetch="all"
    )

    if not results:
        return None

    all_balances = [row["balance"] for row in results]
    coin_holders = [b for b in all_balances if b > 0]
    zero_balance_users = len([b for b in all_balances if b == 0])

    total_users = len(all_balances)
    total_coin_holders = len(coin_holders)
    total_coins = sum(coin_holders)

    # 基本统计
    basic_stats = {
        "total_users": total_users,
        "coin_holders": total_coin_holders,
        "zero_balance_users": zero_balance_users,
        "total_coins_in_circulation": total_coins,
        "avg_coins_per_user": total_coins / total_users if total_users > 0 else 0,
        "avg_coins_per_holder": total_coins / total_coin_holders
        if total_coin_holders > 0
        else 0,
    }

    if not coin_holders:
        return basic_stats

    # 详细统计
    sorted_balances = sorted(coin_holders)

    # 百分位数
    percentiles = calculate_percentiles(
        coin_holders, [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95, 99]
    )

    # 高级统计指标
    advanced_stats = {
        "min_balance": min(coin_holders),
        "max_balance": max(coin_holders),
        "mean": statistics.mean(coin_holders),
        "median": statistics.median(coin_holders),
        "mode": statistics.mode(coin_holders) if coin_holders else 0,
        "std_dev": statistics.stdev(coin_holders) if len(coin_holders) > 1 else 0,
        "variance": statistics.variance(coin_holders) if len(coin_holders) > 1 else 0,
        "skewness": calculate_skewness(coin_holders),
        "kurtosis": calculate_kurtosis(coin_holders),
        "gini_coefficient": calculate_gini_coefficient(coin_holders),
    }

    # 财富集中度分析
    wealth_concentration = {
        "top_1_percent_share": sum(sorted_balances[: int(total_coin_holders * 0.01)])
        / total_coins
        if total_coin_holders > 0
        else 0,
        "top_5_percent_share": sum(sorted_balances[: int(total_coin_holders * 0.05)])
        / total_coins
        if total_coin_holders > 0
        else 0,
        "top_10_percent_share": sum(sorted_balances[: int(total_coin_holders * 0.10)])
        / total_coins
        if total_coin_holders > 0
        else 0,
        "top_20_percent_share": sum(sorted_balances[: int(total_coin_holders * 0.20)])
        / total_coins
        if total_coin_holders > 0
        else 0,
        "top_50_percent_share": sum(sorted_balances[: int(total_coin_holders * 0.50)])
        / total_coins
        if total_coin_holders > 0
        else 0,
    }

    # 余额区间分布
    balance_ranges = {
        "0": zero_balance_users,
        "1-10": len([b for b in coin_holders if 1 <= b <= 10]),
        "11-50": len([b for b in coin_holders if 11 <= b <= 50]),
        "51-100": len([b for b in coin_holders if 51 <= b <= 100]),
        "101-200": len([b for b in coin_holders if 101 <= b <= 200]),
        "201-500": len([b for b in coin_holders if 201 <= b <= 500]),
        "501-1000": len([b for b in coin_holders if 501 <= b <= 1000]),
        "1000+": len([b for b in coin_holders if b > 1000]),
    }

    # Top 富豪榜
    top_wealthy = results[:50]

    return {
        **basic_stats,
        **advanced_stats,
        "percentiles": percentiles,
        "wealth_concentration": wealth_concentration,
        "balance_ranges": balance_ranges,
        "top_wealthy": top_wealthy,
    }


async def analyze_purchasing_power(balance_analysis, shop_analysis):
    """分析用户购买力"""
    print("\n--- 分析用户购买力 ---")

    if not balance_analysis or not balance_analysis.get("coin_holders"):
        return None

    sorted_balances = sorted(
        [row["balance"] for row in balance_analysis.get("top_wealthy", [])]
    )
    all_balances = sorted_balances + [0] * balance_analysis.get("zero_balance_users", 0)
    total_users = len(all_balances)

    # 获取所有商品价格
    all_prices = sorted(
        set(
            [
                item["price"]
                for category in shop_analysis["categories"].values()
                for item in category["items"]
            ]
        )
    )

    # 分析每个价格点的购买力
    purchasing_power = {}
    for price in all_prices:
        if price == 0:
            continue
        users_can_afford = len([b for b in all_balances if b >= price])
        percentage = (users_can_afford / total_users) * 100 if total_users > 0 else 0
        purchasing_power[price] = {
            "users_can_afford": users_can_afford,
            "percentage": percentage,
            "affordability": "高"
            if percentage > 50
            else "中"
            if percentage > 20
            else "低",
        }

    return purchasing_power


def generate_markdown_report(shop_analysis, balance_analysis, purchasing_power):
    """生成Markdown格式的报告"""
    lines = []
    lines.append("# 类脑币经济分析报告")
    lines.append(f"**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # --- 商品价格分析 ---
    lines.append("## 📦 商品价格分析")
    lines.append(f"**商品总数:** {shop_analysis['total_items']}")
    lines.append(
        f"**免费商品数量:** {shop_analysis['price_distribution']['free_items']}"
    )
    lines.append(
        f"**价格范围:** {shop_analysis['price_distribution']['min']} - {shop_analysis['price_distribution']['max']} 类脑币"
    )
    lines.append(
        f"**平均价格:** {shop_analysis['price_distribution']['mean']:.2f} 类脑币"
    )
    lines.append(
        f"**价格中位数:** {shop_analysis['price_distribution']['median']} 类脑币\n"
    )

    lines.append("### 价格区间分布")
    lines.append("| 价格区间 | 商品数量 | 占比 |")
    lines.append("|:---|:---|:---|")
    total_items = shop_analysis["total_items"]
    for range_name, count in sorted(
        shop_analysis["price_distribution"]["price_ranges"].items()
    ):
        percentage = (count / total_items) * 100 if total_items > 0 else 0
        lines.append(f"| {range_name} | {count} | {percentage:.1f}% |")
    lines.append("")

    lines.append("### 各分类商品详情")
    for category, data in shop_analysis["categories"].items():
        lines.append(f"\n#### {category}")
        lines.append(f"- 商品数量: {data['count']}")
        lines.append(f"- 价格范围: {data['min_price']} - {data['max_price']} 类脑币")
        lines.append(f"- 平均价格: {data['avg_price']:.2f} 类脑币")
        lines.append("\n| 商品名称 | 价格 | 描述 |")
        lines.append("|:---|:---|:---|")
        for item in data["items"]:
            lines.append(
                f"| {item['name']} | {item['price']} | {item['description'][:50]}... |"
            )

    # --- 用户余额分析 ---
    if balance_analysis:
        lines.append("\n\n## 👥 用户余额分析")
        lines.append(f"**总用户数:** {balance_analysis['total_users']}")
        lines.append(f"**持有类脑币的用户:** {balance_analysis['coin_holders']}")
        lines.append(f"**零余额用户:** {balance_analysis['zero_balance_users']}")
        lines.append(
            f"**类脑币总流通量:** {balance_analysis['total_coins_in_circulation']:,}"
        )
        lines.append(f"**人均持有量:** {balance_analysis['avg_coins_per_user']:.2f}")
        lines.append(
            f"**持有人均持有量:** {balance_analysis['avg_coins_per_holder']:.2f}\n"
        )

        lines.append("### 核心统计指标")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|:---|:---|:---|")
        lines.append(
            f"| 最高余额 | {balance_analysis['max_balance']:,} | 最富有用户的余额 |"
        )
        lines.append(
            f"| 最低余额 (非零) | {balance_analysis['min_balance']} | 持币用户中最少的余额 |"
        )
        lines.append(
            f"| 平均余额 (Mean) | {balance_analysis['mean']:.2f} | 所有持币用户的平均值 |"
        )
        lines.append(
            f"| 中位数余额 (Median) | {balance_analysis['median']:.2f} | 50%用户低于此值 |"
        )
        lines.append(
            f"| 众数 (Mode) | {balance_analysis['mode']} | 出现频率最高的余额 |"
        )
        lines.append(
            f"| 标准差 (Std Dev) | {balance_analysis['std_dev']:.2f} | 余额离散程度 |"
        )
        lines.append(
            f"| 方差 (Variance) | {balance_analysis['variance']:.2f} | 余额波动程度 |"
        )
        lines.append("")

        lines.append("### 高级统计指标")
        lines.append("| 指标 | 数值 | 说明 |")
        lines.append("|:---|:---|:---|")
        skewness = balance_analysis["skewness"]
        skew_desc = (
            "右偏（富人多）"
            if skewness > 0
            else "左偏（穷人多）"
            if skewness < 0
            else "对称分布"
        )
        lines.append(f"| 偏度 (Skewness) | {skewness:.4f} | {skew_desc} |")
        kurtosis = balance_analysis["kurtosis"]
        kurt_desc = (
            "尖峰（集中）"
            if kurtosis > 0
            else "平峰（分散）"
            if kurtosis < 0
            else "正态分布"
        )
        lines.append(f"| 峰度 (Kurtosis) | {kurtosis:.4f} | {kurt_desc} |")
        gini = balance_analysis["gini_coefficient"]
        gini_desc = (
            "高度不平等" if gini > 0.4 else "中等不平等" if gini > 0.3 else "相对平等"
        )
        lines.append(f"| 基尼系数 (Gini) | {gini:.4f} | {gini_desc} |")
        lines.append("")

        lines.append("### 余额百分位数分布")
        lines.append("| 百分位 | 余额 | 含义 |")
        lines.append("|:---|:---|:---|")
        for p, value in sorted(balance_analysis["percentiles"].items()):
            lines.append(f"| {p}% | {value} | {p}%的用户余额低于此值 |")
        lines.append("")

        lines.append("### 余额区间分布")
        lines.append("| 余额区间 | 用户数 | 占比 |")
        lines.append("|:---|:---|:---|")
        total_users = balance_analysis["total_users"]
        for range_name, count in sorted(balance_analysis["balance_ranges"].items()):
            percentage = (count / total_users) * 100 if total_users > 0 else 0
            lines.append(f"| {range_name} | {count} | {percentage:.2f}% |")
        lines.append("")

        lines.append("### 财富集中度分析")
        lines.append("| 群体 | 持币比例 | 说明 |")
        lines.append("|:---|:---|:---|")
        for group, share in balance_analysis["wealth_concentration"].items():
            group_name = group.replace("_", " ").title()
            lines.append(
                f"| {group_name} | {share * 100:.2f}% | 该群体持有的类脑币占总流通量的比例 |"
            )
        lines.append("")

        lines.append("### Top 50 富豪榜")
        lines.append("| 排名 | 用户ID | 余额 |")
        lines.append("|:---|:---|:---|")
        for i, row in enumerate(balance_analysis["top_wealthy"]):
            rank = i + 1
            user_id = row["user_id"]
            balance = row["balance"]
            lines.append(f"| {rank} | `{user_id}` | {balance:,} |")

    # --- 购买力分析 ---
    if purchasing_power:
        lines.append("\n\n## 💰 用户购买力分析")
        lines.append("各价格点用户的购买能力分析\n")
        lines.append("| 商品价格 | 能购买的用户数 | 占比 | 购买力评级 |")
        lines.append("|:---|:---|:---|:---|")
        for price in sorted(purchasing_power.keys()):
            data = purchasing_power[price]
            lines.append(
                f"| {price} | {data['users_can_afford']} | {data['percentage']:.2f}% | {data['affordability']} |"
            )

    # --- 定价建议 ---
    lines.append("\n\n## 📋 商品定价策略建议")

    if balance_analysis:
        p25 = balance_analysis["percentiles"].get(25, 0)
        p50 = balance_analysis["median"]
        p75 = balance_analysis["percentiles"].get(75, 0)
        p90 = balance_analysis["percentiles"].get(90, 0)
        p95 = balance_analysis["percentiles"].get(95, 0)

        lines.append("### 基于用户财富分布的定价建议")
        lines.append(f"- **🟢 普通消耗品 (1-{int(p50)}类脑币)**")
        lines.append("  - 目标用户: 50%以上的用户")
        lines.append(f"  - 建议定价: 1-{int(p50)} 类脑币")
        lines.append(f"  - 参考指标: 中位数({p50:.0f})、25百分位({p25:.0f})")
        lines.append("  - 适用商品: 日常食品、小礼物等高频消耗品")
        lines.append("")

        lines.append(f"- **🟡 中级商品 ({int(p50) + 1}-{int(p75)}类脑币)**")
        lines.append("  - 目标用户: 25%-50%的活跃用户")
        lines.append(f"  - 建议定价: {int(p50) + 1}-{int(p75)} 类脑币")
        lines.append(f"  - 参考指标: 75百分位({p75:.0f})")
        lines.append("  - 适用商品: 特殊功能、中等价值礼物")
        lines.append("")

        lines.append(f"- **🟠 高级商品 ({int(p75) + 1}-{int(p90)}类脑币)**")
        lines.append("  - 目标用户: 10%-25%的富裕用户")
        lines.append(f"  - 建议定价: {int(p75) + 1}-{int(p90)} 类脑币")
        lines.append(f"  - 参考指标: 90百分位({p90:.0f})")
        lines.append("  - 适用商品: 高级功能、稀有物品")
        lines.append("")

        lines.append(f"- **🔴 奢侈限定品 ({int(p90) + 1}+类脑币)**")
        lines.append("  - 目标用户: 10%以下的顶级玩家")
        lines.append(f"  - 建议定价: {int(p90) + 1}+ 类脑币")
        lines.append(
            f"  - 参考指标: 95百分位({p95:.0f})、最高余额({balance_analysis['max_balance']})"
        )
        lines.append("  - 适用商品: 限定功能、特殊身份标识")

    lines.append("\n\n### 基于购买力分析的定价建议")
    if purchasing_power:
        high_affordability = [
            p for p, d in purchasing_power.items() if d["affordability"] == "高"
        ]
        medium_affordability = [
            p for p, d in purchasing_power.items() if d["affordability"] == "中"
        ]
        low_affordability = [
            p for p, d in purchasing_power.items() if d["affordability"] == "低"
        ]

        lines.append(
            f"- **高购买力价格区间 (50%+用户能买):** {min(high_affordability) if high_affordability else 0}-{max(high_affordability) if high_affordability else 0} 类脑币"
        )
        lines.append(
            f"- **中等购买力价格区间 (20%-50%用户能买):** {min(medium_affordability) if medium_affordability else 0}-{max(medium_affordability) if medium_affordability else 0} 类脑币"
        )
        lines.append(
            f"- **低购买力价格区间 (20%以下用户能买):** {min(low_affordability) if low_affordability else 0}+ 类脑币"
        )

    lines.append("\n\n### 经济健康度评估")
    if balance_analysis:
        gini = balance_analysis["gini_coefficient"]
        if gini < 0.3:
            health = "🟢 健康 - 财富分配相对平等"
        elif gini < 0.4:
            health = "🟡 中等 - 存在一定财富差距"
        else:
            health = "🔴 警告 - 财富分配不均严重"
        lines.append(f"- **基尼系数:** {gini:.4f} - {health}")

        concentration = balance_analysis["wealth_concentration"]["top_10_percent_share"]
        if concentration < 0.3:
            wealth_desc = "财富分散"
        elif concentration < 0.5:
            wealth_desc = "财富适中集中"
        else:
            wealth_desc = "财富高度集中"
        lines.append(
            f"- **Top 10%财富占比:** {concentration * 100:.2f}% - {wealth_desc}"
        )

        inflation_risk = (
            "高"
            if balance_analysis["avg_coins_per_holder"] > 500
            else "中"
            if balance_analysis["avg_coins_per_holder"] > 200
            else "低"
        )
        lines.append(
            f"- **通胀风险:** {inflation_risk} (人均持有: {balance_analysis['avg_coins_per_holder']:.2f})"
        )

    lines.append("\n\n---")
    lines.append(f"*报告生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


async def main():
    """主函数"""
    print("=" * 60)
    print("类脑币经济分析工具")
    print("=" * 60)

    # 初始化数据库
    print("\n正在连接数据库...")
    await chat_db_manager.init_async()
    print("数据库连接成功!")

    # 分析商品
    shop_analysis = await analyze_shop_items()

    # 分析用户余额
    balance_analysis = await analyze_user_balances()

    # 分析购买力
    purchasing_power = None
    if balance_analysis and shop_analysis:
        purchasing_power = await analyze_purchasing_power(
            balance_analysis, shop_analysis
        )

    # 生成报告
    print("\n正在生成报告...")
    report_content = generate_markdown_report(
        shop_analysis, balance_analysis, purchasing_power
    )

    # 写入文件
    reports_dir = os.path.join(ROOT_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    file_path = os.path.join(reports_dir, f"coin_economy_analysis_{timestamp}.md")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print("\n✅ 报告生成成功!")
    print(f"📄 文件路径: {file_path}")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
