from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


REQUIRED_KEYS = [
    "项目简称",
    "成立时间",
    "城市",
    "主营业务",
    "价值",
    "项目来源和录入时间",
    "备注",
]
SECTIONS = ["1.团队", "2.股权结构", "3.产品", "4.技术", "5.生产、客户", "6.市场", "7.收入"]
BANNED_BROAD_BUSINESS = {"半导体材料", "元器件", "设备", "测试机", "新材料"}
HYPE = ["全球领先", "国内唯一", "行业第一", "绝对领先", "填补国内空白", "填补空白"]
LOW_BIT_BANNED = ["领先", "唯一", "首创", "优质", "资深", "显著", "快速", "深度", "强大", "完善", "重要", "持续", "全面", "丰富", "良好"]
SOURCE_TAGS = ["BP", "纪要", "摘要", "工商", "QCC", "企查查", "财报", "官网", "公告", "其他文件", "路演", "逐字稿"]
REMOVED_KEYS = ["是否通过"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("draft", type=Path)
    args = parser.parse_args()

    data = json.loads(args.draft.read_text(encoding="utf-8-sig"))
    errors: list[str] = []
    warnings: list[str] = []

    for key in REQUIRED_KEYS:
        if not str(data.get(key, "")).strip():
            errors.append(f"缺少必需字段：{key}")

    for key in REMOVED_KEYS:
        if key in data and str(data.get(key, "")).strip():
            errors.append(f"新版项目表已取消字段：{key}，不得写入")

    business = str(data.get("主营业务", "")).strip()
    if business in BANNED_BROAD_BUSINESS:
        errors.append("主营业务过于宽泛，需写到具体产品或解决方案")
    if len(business) > 55:
        warnings.append("主营业务超过55个字符，建议压缩")
    if len(business) < 6:
        warnings.append("主营业务可能过短或过于宽泛")

    value = str(data.get("价值", ""))
    positions = []
    for section in SECTIONS:
        pos = value.find(section)
        positions.append(pos)
        if pos < 0:
            errors.append(f"价值栏缺少章节：{section}")
    if all(pos >= 0 for pos in positions) and positions != sorted(positions):
        errors.append("价值栏七个章节顺序不正确")
    if len(value) > 1600:
        warnings.append("价值栏超过1600个字符，建议按低 bit 写法压缩")
    if 0 < len(value) < 350:
        warnings.append("价值栏少于350个字符，请确认是否遗漏关键事实")

    for phrase in HYPE:
        if phrase in value:
            warnings.append(f"发现宣传性表述“{phrase}”，需核查或降格为公司主张")
    for phrase in LOW_BIT_BANNED:
        if phrase in value or phrase in business:
            warnings.append(f"发现非白描词“{phrase}”，优先改为数字、年份、状态或删除")

    if re.search(r"预计|计划|目标", value) is None and re.search(r"202[6-9]年", value):
        warnings.append("价值栏含未来年份但未发现预计/计划/目标等限定词")

    if str(data.get("否决原因", "")).strip():
        warnings.append("否决原因已有内容，请确认这是用户明确提供的投资判断")

    note = str(data.get("备注", "")).strip()
    if note and not any(tag in note for tag in SOURCE_TAGS):
        warnings.append("备注需标明资料来源组合，如：资料来源：BP、纪要、QCC")
    if "冲突" in note and "：" not in note:
        warnings.append("备注含冲突时需保留冲突口径，格式如：冲突：BP为...；纪要为...")

    result = {"valid": not errors, "errors": errors, "warnings": warnings}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
