from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class RouteSpec:
    name: str
    utterances: List[str]
    description: str


MODEL_ROUTE_SPECS = [
    RouteSpec(
        name="simple",
        description="Short, direct questions that can be answered with lightweight reasoning.",
        utterances=[
            "What is RAG?",
            "Explain transformer in one paragraph.",
            "Summarize this short text.",
            "Translate this sentence.",
            "Calculate 2 + 2.",
            "Define attention mechanism.",
            "Give a quick example of overfitting.",
            "这个概念是什么意思？",
            "简单解释一下什么是向量数据库。",
            "一句话回答这个问题。",
            "帮我润色这句话。",
            "列出三个要点。",
        ],
    ),
    RouteSpec(
        name="complex",
        description="Long, multi-step, architectural, coding, debugging, or research analysis tasks.",
        utterances=[
            "Design a complete RAG evaluation pipeline and explain tradeoffs.",
            "Compare these approaches and recommend an implementation plan.",
            "Debug this code and explain the root cause.",
            "Analyze the paper method, limitations, and possible improvements.",
            "Write a full implementation with tests.",
            "Give a step by step proof and discuss edge cases.",
            "Create an architecture for a production research assistant.",
            "详细分析这个系统的架构并给出优化方案。",
            "帮我实现完整功能并补充测试。",
            "比较多个方案的优缺点，然后给出落地计划。",
            "排查这段代码的问题，解释原因并修复。",
            "需要多步推理、设计和权衡。",
        ],
    ),
]
