""" 晋宁会馆·秃贝五边形 5.0 AI 客户端层
职责：
1. 获取 API Key
2. 负责调用 DeepSeek (SiliconFlow)
3. 根据 use_history 决定是否使用 CONTEXT_CACHE
4. 将 API 调用从主流程文件中拆出，降低耦合

说明：
- 本文件不负责 matcher 逻辑
- 不负责 prompt 生成
- 只负责“给模型发消息并取回结果”
"""
from __future__ import annotations

import httpx
import logging
import time
from pathlib import Path

from .context_store import (
    CONTEXT_CACHE,
    MAX_CONTEXT_LEN,
    cleanup_expired_contexts,
)

logger = logging.getLogger("tubei.chat")


def get_api_key() -> str:
    """从 .env.prod 中读取 SILICONFLOW_API_KEY。"""
    try:
        env_path = Path.cwd() / ".env.prod"
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "SILICONFLOW_API_KEY" in line:
                        return line.split("=")[1].strip().replace('"', "").replace("'", "")
    except Exception:
        pass
    return ""


async def chat_with_deepseek(
    context_key: str,
    prompt: str,
    system_prompt: str = "",
    use_history: bool = True,
) -> str:
    """调用 DeepSeek-V3。
    
    参数：
    - context_key: 连续对话缓存 key
    - prompt: 本次 user prompt
    - system_prompt: system prompt
    - use_history:
        True  -> 使用并更新 CONTEXT_CACHE
        False -> 本次调用无历史上下文，不写回 CONTEXT_CACHE

    返回：
    - 模型回复文本
    """
    api_key = get_api_key()
    if not api_key:
        return "(错误：未配置 API Key)"

    cleanup_expired_contexts()

    history = []

    if use_history:
        if context_key not in CONTEXT_CACHE:
            CONTEXT_CACHE[context_key] = {
                "messages": [],
                "last_active": time.time(),
            }

        ctx = CONTEXT_CACHE[context_key]
        ctx["last_active"] = time.time()
        history = ctx["messages"]
    else:
        ctx = None

    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": prompt}
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-ai/DeepSeek-V3",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 512,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.siliconflow.cn/v1/chat/completions",
                json=payload,
                headers=headers,
            )

        if resp.status_code == 200:
            reply = resp.json()["choices"][0]["message"]["content"].strip()

            if use_history and ctx is not None:
                history.append({"role": "user", "content": prompt})
                history.append({"role": "assistant", "content": reply})
                ctx["messages"] = history[-MAX_CONTEXT_LEN * 2:]

            return reply

        return f"(API Error: {resp.status_code})"

    except Exception as e:
        logger.error(f"[Chat] API 调用失败: {e}")
        return "(灵力连接中断)"