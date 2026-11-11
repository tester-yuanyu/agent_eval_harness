"""作者维护的合成输入解码器，不是自然语言模型，不读取期望答案。"""

from __future__ import annotations

import re

INTENT_TO_TOOL = {
    "query_user": "query_user_info",
    "query_gift": "query_gift_info",
    "query_pool": "query_pool_config",
    "query_information": "query_information",
    "prepare_resource": "prepare_resource",
    "add_backpack_gift": "add_gift_to_backpack",
}


def candidate(intent, parameters):
    # Intentionally optimistic candidate: the real contract validator decides status.
    return {
        "intent": intent,
        "parameters": parameters,
        "status": "READY",
        "next_action": "CALL_TOOL",
        "missing_parameters": [],
        "reason": "deterministic reference input; Agent must apply its own policy",
    }


def decode(text):
    text = text.removeprefix("麻烦帮我处理一下：")
    params = {}
    if text in {
        "请预订明天从北京到上海的机票。",
        "请为我创建一幅水彩画。",
        "请播放一首古典音乐。",
    }:
        return candidate("unsupported", {})
    if text == "请查询用户信息。":
        return candidate("query_user", {})
    if text == "请查询手机号 bad-phone 对应的用户。":
        return candidate("query_user", {"phone": "bad-phone"})
    for pattern, intent, field in [
        (r"查询用户 ID (\d+) 的信息。", "query_user", "user_id"),
        (r"查询礼物 ID (?:为 )?(\d+) 的信息。", "query_gift", "gift_id"),
        (r"查询奖池 ID (?:为 )?(\d+) 的配置。", "query_pool", "pool_id"),
    ]:
        match = re.fullmatch(pattern, text)
        if match:
            return candidate(intent, {field: int(match[1])})
    if text in {"请查询礼物信息。", "请查询奖池配置。"}:
        return candidate("query_gift" if "礼物" in text else "query_pool", {})
    if text in {
        "查询 test 环境的账号资源。",
        "请查询账号资源。",
        "查询账号资源，environment 是空字符串。",
    }:
        params = {"resource_type": "账号"}
        if "test" in text:
            params["environment"] = "test"
        elif "空字符串" in text:
            params["environment"] = ""
        return candidate("query_information", params)
    match = re.fullmatch(
        r"(在 test 环境)?准备 (\d+) 个账号资源，request_id 为 ([\w-]+)。", text
    )
    if match:
        params = {
            "resource_type": "账号",
            "count": int(match[2]),
            "request_id": match[3],
        }
        if match[1]:
            params["environment"] = "test"
        return candidate("prepare_resource", params)
    match = re.fullmatch(
        r"(在 test 环境)?给用户 (\d+) 发放礼物 (\d+)，数量 (\d+)，有效期 (\d+) 天。",
        text,
    )
    if match:
        params = dict(
            zip(
                ("user_id", "gift_id", "num", "duration_days"),
                map(int, match.groups()[1:]),
                strict=True,
            )
        )
        if match[1]:
            params["environment"] = "test"
        return candidate("add_backpack_gift", params)
    raise ValueError("no independent reference input recipe for this prompt")
