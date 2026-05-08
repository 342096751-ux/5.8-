def query_knowledge_base(content: str, domain: str = "") -> str:
    """模拟知识库查询，可替换为真实检索逻辑。"""
    if "挂路灯" in content:
        return "历史案例：涉及暴力煽动表达，通常进入高风险复核。"
    if "政治" in content or "资本家" in content:
        return "规则条款：政治仇恨与群体煽动需结合上下文判断恶意程度。"
    return f"模拟知识（{domain or '通用'}）：未找到直接先例。"
