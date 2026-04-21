from __future__ import annotations

import unittest

from autopapers.llm.minimax import MiniMaxError
from autopapers.llm.planner import Planner
from autopapers.models import Paper
from autopapers.pdf import ExtractedPaperContent


class FailingClient:
    def chat_text(self, *args, **kwargs) -> str:
        raise MiniMaxError("overloaded")


class SparseDigestClient:
    def chat_text(self, *args, **kwargs) -> str:
        return '{"major_topic":"CS","minor_topic":"cs.AI","keywords":["agent"]}'


class StructuredDigestClient:
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        if "摘要翻译器" in system_prompt:
            return '{"abstract_zh":"本文分析测试时扩展中验证器设计的作用，研究验证器不完美时性能收益如何变化，并给出结构化理解框架。"}'
        if "论文整理器" in system_prompt:
            return '{"major_topic":"测试时扩展","minor_topic":"验证器设计","keywords":["测试时扩展","验证器","推理"]}'
        if "先把论文讲明白" in system_prompt:
            return (
                '{"one_sentence_takeaway":"本文提出面向测试时扩展的验证器敏感分析框架。",'
                '"problem":"论文研究验证器不完美时，测试时扩展策略的性能如何变化，并给出可操作的分析框架。",'
                '"background":"直觉上，测试时扩展依赖验证器来筛选更好的候选，因此验证器误差会直接放大到最终决策。",'
                '"relevance":"这篇论文适合用来理解 verifier 质量与 test-time scaling 成效之间的关系。"}'
            )
        if "方法解析器" in system_prompt:
            return '{"method":"方法先构造候选答案集合，再用验证器对候选排序并分析误差传播。关键评分形式可写为 $$s(y|x)=\\\\log p(y|x)+\\\\lambda v(y, x)$$，其中 $v$ 是验证器分数，$\\\\lambda$ 控制验证信号权重。"}'
        if "实验分析器" in system_prompt:
            return (
                '{"experiment_setup":"实验在数学推理与代码任务上比较不同验证器精度、候选规模和选择策略，对比 best-of-N 与 verifier-guided reranking。",'
                '"findings":["验证器质量越高，测试时扩展收益越稳定。","验证器存在系统性偏差时，增大候选规模并不会持续提升性能。"],'
                '"limitations":["分析主要聚焦离线评测场景。"],'
                '"improvement_ideas":["引入置信度校准后的验证器。","把验证器不确定性显式纳入选择策略。"]}'
            )
        return "{}"


class CleanupDigestClient:
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        if "摘要翻译器" in system_prompt:
            return '{"abstract_zh":"本文研究人类主观不确定性与大语言模型概率式不确定性度量之间的对齐程度，并讨论这些度量是否能更好支持可信交互。"}'
        if "论文整理器" in system_prompt:
            return '{"major_topic":"LLM不确定性与校准","minor_topic":"人类对齐不确定性","keywords":["不确定性","校准","人类对齐"]}'
        if "先把论文讲明白" in system_prompt:
            return (
                '{"one_sentence_takeaway":"We study how human uncertainty aligns with LLM probability-based uncertainty measures across shared cloze tasks.",'
                '"problem":"The paper asks whether model-side uncertainty can better support calibrated interaction if it aligns with how humans actually feel uncertainty.",'
                '"background":"Humans do not interpret 60% confidence the same way a model does, so probability alone is not yet a usable trust signal.",'
                '"relevance":"This work matters for trustworthy interaction, uncertainty-aware interfaces, and preference-aligned model calibration."}'
            )
        if "方法解析器" in system_prompt:
            return (
                '{"method":"The pipeline has three steps: 1. **Dataset construction**: collect survey responses across multiple waves. '
                '2. **Prompting setup**: use a shared cloze template for humans and models. '
                '3. **Uncertainty measures**: compare self-reported uncertainty, response frequency, nucleus size, and entropy-style scores. '
                '$$NS=|\\\\{v_i:\\\\sum_{j=1}^{|V_k|}P(v_j|q_b)\\\\leq0.95\\\\}|$$"}'
            )
        if "实验分析器" in system_prompt:
            return (
                '{"experiment_setup":"In this section, we present the results of our experiments described in section 4. '
                'We split our analysis into correlation evaluation and predictive modeling.",'
                '"findings":["In the first phase, we evaluate whether human and LLM uncertainty measures are correlated across tasks.",'
                '"Top-3-fold cross validation shows some measures remain stable across models."],'
                '"limitations":["The study still relies on survey-style cloze tasks and does not cover interactive dialogue settings."],'
                '"improvement_ideas":["Extend the evaluation to multi-turn interaction.","Add behavioral calibration signals beyond token probabilities."]}'
            )
        if "中文清洗器" in system_prompt:
            return (
                '{"one_sentence_takeaway":"本文研究人类主观不确定性与大语言模型概率式不确定性度量之间的对齐关系。",'
                '"problem":"论文关注一个核心问题：如果模型的不确定性度量能够更接近人类真实的不确定性感受，是否就能更好地支持可信交互与校准。",'
                '"background":"直觉上，人类对“60% 置信度”的理解和模型内部概率并不一致，因此单纯输出概率还不足以直接作为信任信号。",'
                '"method":"整个方法分为三步。\\n\\n1. **数据集构建**：收集多波次问卷中的完形填空回答。\\n\\n2. **统一提示设置**：让人类和模型在一致模板下作答。\\n\\n3. **不确定性度量比较**：比较自报告不确定性、响应频率、核心集大小和熵类指标。\\n\\n$$NS=|\\\\{v_i:\\\\sum_{j=1}^{|V_k|}P(v_j|q_b)\\\\leq0.95\\\\}|$$",'
                '"experiment_setup":"实验分成两个阶段。\\n\\n第一阶段评估人类不确定性与模型不确定性度量之间的相关性。\\n\\n第二阶段再用这些度量预测人类不确定性，比较不同指标组合的效果。",'
                '"findings":["多种模型不确定性度量与人类主观不确定性存在可观相关性。","不同度量组合后，对人类不确定性的预测效果通常优于单一指标。"],'
                '"limitations":["实验主要基于问卷式完形填空任务，尚未覆盖真实多轮交互场景。"],'
                '"relevance":"这篇论文对理解“模型觉得不确定”和“人类感到不确定”之间的差距很有价值。",'
                '"improvement_ideas":["把评测扩展到多轮交互任务。","引入行为层面的校准信号，而不只依赖 token 概率。"]}'
            )
        return "{}"


class FieldCleanupDigestClient:
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        if "摘要翻译器" in system_prompt:
            return '{"abstract_zh":"本文研究语言模型不确定性是否能够更贴近人类真实的不确定性感受，并探讨其对信任校准的意义。"}'
        if "论文整理器" in system_prompt:
            return '{"major_topic":"LLM不确定性与校准","minor_topic":"人类对齐不确定性","keywords":["不确定性","校准"]}'
        if "先把论文讲明白" in system_prompt:
            return (
                '{"one_sentence_takeaway":"We study human-aligned uncertainty for language models.",'
                '"problem":"The paper asks whether model uncertainty can align with human uncertainty.",'
                '"background":"Human confidence and model confidence are not directly comparable.",'
                '"relevance":"This matters for trust calibration."}'
            )
        if "方法解析器" in system_prompt:
            return '{"method":"We compare multiple uncertainty measures across shared tasks."}'
        if "实验分析器" in system_prompt:
            return (
                '{"experiment_setup":"We evaluate correlation and predictive modeling.",'
                '"findings":["In the first phase, we measure correlation between human and model uncertainty.","Top-3-fold cross validation reports stable trends across models."],'
                '"limitations":["The benchmark is still limited to cloze-style tasks."],'
                '"improvement_ideas":["Extend to dialogue settings."]}'
            )
        if "中文清洗器" in system_prompt and "待清洗字段: findings" in user_prompt:
            return '{"findings":["第一阶段衡量人类不确定性与模型不确定性之间的相关性。","3折交叉验证表明这种趋势在不同模型上相对稳定。"]}'
        if "中文清洗器" in system_prompt:
            return (
                '{"one_sentence_takeaway":"本文研究语言模型不确定性与人类不确定性的对齐问题。",'
                '"problem":"论文关注模型不确定性是否能更贴近人类真实的不确定性感受。",'
                '"background":"人类和模型对置信度的理解并不一致。",'
                '"method":"通过共享任务比较多种不确定性度量。",'
                '"experiment_setup":"实验评估相关性与预测能力。",'
                '"relevance":"这项工作有助于改进信任校准。"}'
            )
        return "{}"


class FinalFormattingDigestClient:
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        if "摘要翻译器" in system_prompt:
            return '{"abstract_zh":"本文系统研究验证器引导的测试时扩展策略。"}'
        if "论文整理器" in system_prompt:
            return '{"major_topic":"测试时计算扩展","minor_topic":"验证器与判断器","keywords":["测试时扩展","验证器"]}'
        if "先把论文讲明白" in system_prompt:
            return (
                '{"one_sentence_takeaway":"本文分析验证器质量如何影响测试时扩展效果。",'
                '"problem":"论文关注验证器质量变化时，候选扩展和重排序策略的收益如何变化。",'
                '"background":"如果验证器本身有系统误差，更大的候选池可能只会放大错误选择。",'
                '"relevance":"这项工作适合用来理解测试时扩展中的验证器边界。"}'
            )
        if "方法解析器" in system_prompt:
            return (
                '{"method":"整个方法分为三步。1. **数据准备**：先统一问题与候选格式。 '
                '2. **候选生成**：为每个问题采样多个答案。 '
                '3. **验证重排**：使用验证器对候选重新排序。 '
                '$$s(y|x)=\\\\log p(y|x)+v(y,x)$$"}'
            )
        if "实验分析器" in system_prompt:
            return (
                '{"experiment_setup":"实验在数学与代码任务上进行，对比不同候选规模和验证策略。",'
                '"findings":["验证器越稳定，测试时扩展收益越可靠。","候选规模继续增大时，错误验证器会放大偏差。"],'
                '"limitations":["分析仍主要基于离线评测。"],'
                '"improvement_ideas":["引入校准后的验证器。"]}'
            )
        if "最终格式规整器" in system_prompt:
            return (
                '{"abstract_zh":"本文系统研究验证器引导的测试时扩展策略。",'
                '"one_sentence_takeaway":"本文分析验证器质量如何影响测试时扩展效果。",'
                '"problem":"论文关注验证器质量变化时，候选扩展和重排序策略的收益如何变化。",'
                '"background":"如果验证器本身有系统误差，更大的候选池可能只会放大错误选择。",'
                '"method":"整个方法分为三步。\\n\\n1. **数据准备**：先统一问题与候选格式。\\n\\n2. **候选生成**：为每个问题采样多个答案。\\n\\n3. **验证重排**：使用验证器对候选重新排序。\\n\\n$$s(y|x)=\\\\log p(y|x)+v(y,x)$$",'
                '"experiment_setup":"实验在数学与代码任务上进行，\\n\\n对比不同候选规模和验证策略。",'
                '"findings":["- 验证器越稳定，测试时扩展收益越可靠。","- 候选规模继续增大时，错误验证器会放大偏差。"],'
                '"limitations":["- 分析仍主要基于离线评测。"],'
                '"relevance":"这项工作适合用来理解测试时扩展中的验证器边界。",'
                '"improvement_ideas":["- 引入校准后的验证器。"]}'
            )
        return "{}"


class FormatRewriteDigestClient(FinalFormattingDigestClient):
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        if "最终格式规整器" in system_prompt:
            return (
                '{"method":"整个方法分为四步。\\n\\n1. **数据准备**：先统一问题与候选格式。\\n\\n2. **候选生成**：为每个问题采样多个答案。\\n\\n3. **验证重排**：使用验证器对候选重新排序。\\n\\n$$s(y|x)=\\\\log p(y|x)+v(y,x)$$",'
                '"findings":["验证器越稳定，测试时扩展收益越可靠。","候选规模继续增大时，正确验证器会放大优势。"]}'
            )
        return super().chat_text(messages, *args, **kwargs)


class FormatFieldFallbackDigestClient(FinalFormattingDigestClient):
    def chat_text(self, messages, *args, **kwargs) -> str:
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        if "最终格式规整器" in system_prompt and "待规整字段:" not in user_prompt:
            return "not valid json"
        if "最终格式规整器" in system_prompt and "待规整字段: method" in user_prompt:
            return '{"method":"整个方法分为三步。\\n\\n1. **数据准备**：先统一问题与候选格式。\\n\\n2. **候选生成**：为每个问题采样多个答案。\\n\\n3. **验证重排**：使用验证器对候选重新排序。\\n\\n$$s(y|x)=\\\\log p(y|x)+v(y,x)$$"}'
        if "最终格式规整器" in system_prompt and "待规整字段: experiment_setup" in user_prompt:
            return '{"experiment_setup":"实验在数学与代码任务上进行，\\n\\n对比不同候选规模和验证策略。"}'
        if "最终格式规整器" in system_prompt and "待规整字段: findings" in user_prompt:
            return '{"findings":["- 验证器越稳定，测试时扩展收益越可靠。","- 候选规模继续增大时，错误验证器会放大偏差。"]}'
        if "最终格式规整器" in system_prompt and "待规整字段: improvement_ideas" in user_prompt:
            return '{"improvement_ideas":["- 引入校准后的验证器。"]}'
        return super().chat_text(messages, *args, **kwargs)


class DiscoverWithExplicitRefsClient:
    def chat_text(self, *args, **kwargs) -> str:
        return (
            '{"intent":"discover_papers","user_goal":"查找8篇test-time scaling相关论文",'
            '"search_query":"test-time scaling LLM inference compute verification ensemble",'
            '"paper_refs":['
            '"ROC-n-reroll: How verifier imperfection affects test-time scaling",'
            '"CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"'
            '],"max_results":8,"reuse_local":true,"rationale":"test"}'
        )


class CapturingClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat_text(self, messages, *args, **kwargs) -> str:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.response


class PlannerResilienceTests(unittest.TestCase):
    def test_plan_request_falls_back_when_llm_fails(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request("帮我找一下新的大模型不确定性的论文", "")

        self.assertEqual(plan.intent, "discover_papers")
        self.assertEqual(plan.max_results, 5)
        self.assertIn("大模型不确定性", plan.search_query)

    def test_plan_request_extracts_clean_paper_reference_on_fallback(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "详细介绍下这个论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            ["Trust but Verify! A Survey on Verification Design for Test-time Scaling"],
        )

    def test_plan_request_treats_bare_title_as_explain_paper_on_fallback(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(plan.search_query, "")
        self.assertEqual(
            plan.paper_refs,
            ["CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"],
        )

    def test_plan_request_extracts_multiple_paper_references_on_fallback(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "请对比这两篇论文：Trust but Verify! A Survey on Verification Design for Test-time Scaling 和 Attention Is All You Need",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            [
                "Trust but Verify! A Survey on Verification Design for Test-time Scaling",
                "Attention Is All You Need",
            ],
        )

    def test_plan_request_treats_explicit_paper_lookup_lists_as_explain_paper(self) -> None:
        planner = Planner(DiscoverWithExplicitRefsClient(), default_max_results=5)

        plan = planner.plan_request(
            "找一下这几篇论文：1. ROC-n-reroll: How verifier imperfection affects test-time scaling "
            "2. CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(plan.search_query, "")
        self.assertEqual(
            plan.paper_refs,
            [
                "ROC-n-reroll: How verifier imperfection affects test-time scaling",
                "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
            ],
        )

    def test_plan_request_uses_json_schema_response_format_and_strict_json_prompt(self) -> None:
        client = CapturingClient(
            '{"intent":"explain_paper","user_goal":"介绍论文","search_query":"","paper_refs":["CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning"],"max_results":1,"reuse_local":true,"rationale":"test"}'
        )
        planner = Planner(client, default_max_results=5)

        plan = planner.plan_request("CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning", "")

        self.assertEqual(plan.intent, "explain_paper")
        call = client.calls[0]
        response_format = call["kwargs"]["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertEqual(response_format["json_schema"]["name"], "request_plan")
        self.assertIn("你必须严格输出一个 JSON 对象", call["messages"][0]["content"])
        self.assertIn("输出检查清单", call["messages"][1]["content"])

    def test_plan_request_logs_raw_response_on_parse_failure(self) -> None:
        client = CapturingClient("这里是解释，不是 JSON。")
        planner = Planner(client, default_max_results=5)
        debug_logs: list[str] = []

        plan = planner.plan_request("CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning", "", debug_callback=debug_logs.append)

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(len(debug_logs), 1)
        self.assertIn("任务规划 原始模型返回（解析失败）", debug_logs[0])
        self.assertIn("这里是解释，不是 JSON", debug_logs[0])

    def test_fallback_plan_extracts_numbered_paper_lists(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)

        plan = planner.plan_request(
            "找一下这几篇论文： 1. ROC-n-reroll: How verifier imperfection affects test-time scaling "
            "2. CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning "
            "3. ATTS: Asynchronous Test-Time Scaling via Conformal Prediction",
            "",
        )

        self.assertEqual(plan.intent, "explain_paper")
        self.assertEqual(
            plan.paper_refs,
            [
                "ROC-n-reroll: How verifier imperfection affects test-time scaling",
                "CaTS: Calibrated Test-Time Scaling for Efficient LLM Reasoning",
                "ATTS: Asynchronous Test-Time Scaling via Conformal Prediction",
            ],
        )

    def test_digest_paper_falls_back_when_llm_fails(self) -> None:
        planner = Planner(FailingClient(), default_max_results=5)
        paper = Paper(
            paper_id="2401.12345",
            source_primary="arxiv",
            arxiv_id="2401.12345",
            versioned_id="2401.12345v1",
            title="Test Driven Agents",
            abstract=(
                "Reliable agents benefit from explicit verification loops. "
                "The study evaluates the effect of verification on accuracy under tool failure. "
                "Results show more stable recovery after intermediate mistakes."
            ),
            authors=["Alice"],
            published="2026-01-01T00:00:00Z",
            updated="2026-01-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2401.12345v1",
            entry_url="http://arxiv.org/abs/2401.12345v1",
            pdf_url="http://arxiv.org/pdf/2401.12345v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )

        digest = planner.digest_paper("介绍这篇论文", paper, "", [])

        self.assertEqual(digest.major_topic, "CS")
        self.assertEqual(digest.minor_topic, "cs.AI")
        self.assertEqual(digest.abstract_zh, "")
        self.assertEqual(digest.one_sentence_takeaway, "Reliable agents benefit from explicit verification loops.")
        self.assertEqual(
            digest.findings,
            [
                "Reliable agents benefit from explicit verification loops.",
                "The study evaluates the effect of verification on accuracy under tool failure.",
            ],
        )
        self.assertNotIn("...", digest.one_sentence_takeaway)
        self.assertFalse(any("..." in finding for finding in digest.findings))
        self.assertEqual(digest.experiment_setup, "")
        self.assertEqual(digest.improvement_ideas, [])

    def test_digest_paper_logs_raw_response_when_json_parse_fails(self) -> None:
        client = CapturingClient("method: explain it in prose")
        planner = Planner(client, default_max_results=5)
        paper = Paper(
            paper_id="2401.12345",
            source_primary="arxiv",
            arxiv_id="2401.12345",
            versioned_id="2401.12345v1",
            title="Test Driven Agents",
            abstract="Reliable agents benefit from explicit verification loops.",
            authors=["Alice"],
            published="2026-01-01T00:00:00Z",
            updated="2026-01-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2401.12345v1",
            entry_url="http://arxiv.org/abs/2401.12345v1",
            pdf_url="http://arxiv.org/pdf/2401.12345v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )
        debug_logs: list[str] = []

        digest = planner.digest_paper(
            "介绍这篇论文",
            paper,
            ExtractedPaperContent(method="Method section."),
            [],
            debug_callback=debug_logs.append,
        )

        self.assertTrue(debug_logs)
        self.assertIn("原始模型返回（解析失败）", debug_logs[0])
        self.assertIn("method: explain it in prose", debug_logs[0])
        first_call = client.calls[0]
        self.assertEqual(first_call["kwargs"]["response_format"]["type"], "json_schema")
        self.assertEqual(first_call["kwargs"]["response_format"]["json_schema"]["name"], "abstract_translation")
        self.assertEqual(digest.one_sentence_takeaway, "Reliable agents benefit from explicit verification loops.")

    def test_digest_paper_uses_pdf_sections_for_fallbacks_when_response_is_sparse(self) -> None:
        planner = Planner(SparseDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2401.12346",
            source_primary="arxiv",
            arxiv_id="2401.12346",
            versioned_id="2401.12346v1",
            title="Sparse Digest Recovery",
            abstract=(
                "This paper studies resilient summary generation for paper libraries. "
                "It shows that sentence-based fallbacks preserve note readability better than clipped snippets."
            ),
            authors=["Bob"],
            published="2026-01-03T00:00:00Z",
            updated="2026-01-03T00:00:00Z",
            entry_id="http://arxiv.org/abs/2401.12346v1",
            entry_url="http://arxiv.org/abs/2401.12346v1",
            pdf_url="http://arxiv.org/pdf/2401.12346v1",
            primary_category="cs.CL",
            categories=["cs.CL"],
        )
        extracted = ExtractedPaperContent(
            abstract="We study resilient summary generation for paper libraries.",
            introduction="The intuition is that section-aware parsing preserves the paper's logical structure.",
            method="Our method parses PDFs into sections and then summarizes each section separately.",
            experiments=(
                "We evaluate on agent papers and benchmark whether section-aware parsing reduces hallucinated notes. "
                "The setup compares abstract-only summaries against PDF-grounded summaries. "
                "Section-aware parsing preserves note readability better than clipped snippets."
            ),
            conclusion="A limitation is that OCR-heavy PDFs remain difficult. Future work can combine layout-aware parsers.",
            equations=["q(d)=\\alpha s(d)+\\beta r(d)"],
        )

        digest = planner.digest_paper("介绍这篇论文", paper, extracted, [])

        self.assertEqual(digest.abstract_zh, "")
        self.assertEqual(
            digest.one_sentence_takeaway,
            "We study resilient summary generation for paper libraries.",
        )
        self.assertEqual(
            digest.findings,
            [
                "We evaluate on agent papers and benchmark whether section-aware parsing reduces hallucinated notes.",
                "The setup compares abstract-only summaries against PDF-grounded summaries.",
                "Section-aware parsing preserves note readability better than clipped snippets.",
            ],
        )
        self.assertIn("Our method parses PDFs into sections", digest.method)
        self.assertIn("q(d)=\\alpha s(d)+\\beta r(d)", digest.method)
        self.assertIn("The setup compares abstract-only summaries", digest.experiment_setup)
        self.assertEqual(
            digest.limitations,
            [
                "A limitation is that OCR-heavy PDFs remain difficult.",
                "Future work can combine layout-aware parsers.",
            ],
        )
        self.assertEqual(digest.improvement_ideas, ["Future work can combine layout-aware parsers."])
        self.assertNotIn("...", digest.one_sentence_takeaway)
        self.assertFalse(any("..." in finding for finding in digest.findings))

    def test_digest_paper_merges_staged_structured_outputs(self) -> None:
        planner = Planner(StructuredDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2604.12345",
            source_primary="arxiv",
            arxiv_id="2604.12345",
            versioned_id="2604.12345v1",
            title="Verifier-Aware Scaling",
            abstract="We analyze verifier-aware scaling for reasoning systems.",
            authors=["Carol"],
            published="2026-04-01T00:00:00Z",
            updated="2026-04-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2604.12345v1",
            entry_url="http://arxiv.org/abs/2604.12345v1",
            pdf_url="http://arxiv.org/pdf/2604.12345v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )
        extracted = ExtractedPaperContent(
            abstract="This paper studies verifier-aware test-time scaling.",
            introduction="Verifier quality determines whether larger candidate pools are useful.",
            method="We analyze error propagation under reranking.",
            experiments="We vary verifier quality and candidate budget on reasoning tasks.",
            conclusion="Future work studies calibrated verifiers.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertEqual(digest.major_topic, "测试时扩展")
        self.assertEqual(digest.minor_topic, "验证器设计")
        self.assertIn("验证器设计的作用", digest.abstract_zh)
        self.assertEqual(digest.one_sentence_takeaway, "本文提出面向测试时扩展的验证器敏感分析框架。")
        self.assertIn("验证器不完美时", digest.problem)
        self.assertIn("验证器误差会直接放大", digest.background)
        self.assertIn("$$s(y|x)=\\log p(y|x)+\\lambda v(y, x)$$", digest.method)
        self.assertIn("best-of-N", digest.experiment_setup)
        self.assertEqual(
            digest.findings,
            [
                "验证器质量越高，测试时扩展收益越稳定。",
                "验证器存在系统性偏差时，增大候选规模并不会持续提升性能。",
            ],
        )
        self.assertEqual(digest.limitations, ["分析主要聚焦离线评测场景。"])
        self.assertEqual(
            digest.improvement_ideas,
            ["引入置信度校准后的验证器。", "把验证器不确定性显式纳入选择策略。"],
        )

    def test_digest_paper_runs_cleanup_for_english_dense_output(self) -> None:
        planner = Planner(CleanupDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2503.12528",
            source_primary="arxiv",
            arxiv_id="2503.12528",
            versioned_id="2503.12528v1",
            title="Investigating Human-Aligned Large Language Model Uncertainty",
            abstract="We investigate human-aligned large language model uncertainty.",
            authors=["Dana"],
            published="2025-03-01T00:00:00Z",
            updated="2025-03-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2503.12528v1",
            entry_url="http://arxiv.org/abs/2503.12528v1",
            pdf_url="http://arxiv.org/pdf/2503.12528v1",
            primary_category="cs.CL",
            categories=["cs.CL"],
        )
        extracted = ExtractedPaperContent(
            abstract="We investigate whether human uncertainty aligns with model uncertainty.",
            introduction="Humans and models interpret confidence in different ways.",
            method="We compare several uncertainty measures under a shared cloze-task protocol.",
            experiments="We split the analysis into correlation evaluation and predictive modeling.",
            conclusion="Future work should extend the benchmark to interactive settings.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertEqual(digest.major_topic, "LLM不确定性与校准")
        self.assertEqual(digest.minor_topic, "人类对齐不确定性")
        self.assertIn("主观不确定性", digest.abstract_zh)
        self.assertIn("人类主观不确定性", digest.one_sentence_takeaway)
        self.assertIn("\n\n1. **数据集构建**", digest.method)
        self.assertIn("$$NS=|\\{v_i:\\sum_{j=1}^{|V_k|}P(v_j|q_b)\\leq0.95\\}|$$", digest.method)
        self.assertIn("实验分成两个阶段。", digest.experiment_setup)
        self.assertNotIn("In this section", digest.experiment_setup)
        self.assertEqual(
            digest.findings,
            [
                "多种模型不确定性度量与人类主观不确定性存在可观相关性。",
                "不同度量组合后，对人类不确定性的预测效果通常优于单一指标。",
            ],
        )

    def test_digest_paper_runs_field_level_cleanup_for_remaining_english_lists(self) -> None:
        planner = Planner(FieldCleanupDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2503.12528",
            source_primary="arxiv",
            arxiv_id="2503.12528",
            versioned_id="2503.12528v1",
            title="Investigating Human-Aligned Large Language Model Uncertainty",
            abstract="We investigate human-aligned large language model uncertainty.",
            authors=["Dana"],
            published="2025-03-01T00:00:00Z",
            updated="2025-03-02T00:00:00Z",
            entry_id="http://arxiv.org/abs/2503.12528v1",
            entry_url="http://arxiv.org/abs/2503.12528v1",
            pdf_url="http://arxiv.org/pdf/2503.12528v1",
            primary_category="cs.CL",
            categories=["cs.CL"],
        )
        extracted = ExtractedPaperContent(
            abstract="We investigate whether human uncertainty aligns with model uncertainty.",
            introduction="Humans and models interpret confidence in different ways.",
            method="We compare several uncertainty measures under a shared cloze-task protocol.",
            experiments="We split the analysis into correlation evaluation and predictive modeling.",
            conclusion="Future work should extend the benchmark to interactive settings.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertIn("信任校准", digest.abstract_zh)
        self.assertEqual(
            digest.findings,
            [
                "第一阶段衡量人类不确定性与模型不确定性之间的相关性。",
                "3折交叉验证表明这种趋势在不同模型上相对稳定。",
            ],
        )

    def test_digest_paper_runs_final_format_tightening_after_staged_generation(self) -> None:
        planner = Planner(FinalFormattingDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2604.20001",
            source_primary="arxiv",
            arxiv_id="2604.20001",
            versioned_id="2604.20001v1",
            title="Verifier-Guided Test-Time Scaling",
            abstract="We study verifier-guided test-time scaling.",
            authors=["Eve"],
            published="2026-04-10T00:00:00Z",
            updated="2026-04-11T00:00:00Z",
            entry_id="http://arxiv.org/abs/2604.20001v1",
            entry_url="http://arxiv.org/abs/2604.20001v1",
            pdf_url="http://arxiv.org/pdf/2604.20001v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )
        extracted = ExtractedPaperContent(
            abstract="We study verifier-guided test-time scaling.",
            introduction="Verifier quality changes the value of larger candidate pools.",
            method="We compare candidate generation and reranking.",
            experiments="We evaluate math and code reasoning tasks.",
            conclusion="Future work studies calibrated verifiers.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertIn("\n\n1. **数据准备**", digest.method)
        self.assertIn("\n\n2. **候选生成**", digest.method)
        self.assertIn("\n\n$$s(y|x)=\\log p(y|x)+v(y,x)$$", digest.method)
        self.assertEqual(digest.experiment_setup, "实验在数学与代码任务上进行，\n\n对比不同候选规模和验证策略。")
        self.assertEqual(
            digest.findings,
            [
                "验证器越稳定，测试时扩展收益越可靠。",
                "候选规模继续增大时，错误验证器会放大偏差。",
            ],
        )
        self.assertEqual(digest.improvement_ideas, ["引入校准后的验证器。"])

    def test_digest_paper_rejects_formatter_rewrites_and_keeps_original_content(self) -> None:
        planner = Planner(FormatRewriteDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2604.20002",
            source_primary="arxiv",
            arxiv_id="2604.20002",
            versioned_id="2604.20002v1",
            title="Verifier-Guided Test-Time Scaling",
            abstract="We study verifier-guided test-time scaling.",
            authors=["Eve"],
            published="2026-04-10T00:00:00Z",
            updated="2026-04-11T00:00:00Z",
            entry_id="http://arxiv.org/abs/2604.20002v1",
            entry_url="http://arxiv.org/abs/2604.20002v1",
            pdf_url="http://arxiv.org/pdf/2604.20002v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )
        extracted = ExtractedPaperContent(
            abstract="We study verifier-guided test-time scaling.",
            introduction="Verifier quality changes the value of larger candidate pools.",
            method="We compare candidate generation and reranking.",
            experiments="We evaluate math and code reasoning tasks.",
            conclusion="Future work studies calibrated verifiers.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertIn("整个方法分为三步。1. **数据准备**", digest.method)
        self.assertNotIn("整个方法分为四步", digest.method)
        self.assertEqual(
            digest.findings,
            [
                "验证器越稳定，测试时扩展收益越可靠。",
                "候选规模继续增大时，错误验证器会放大偏差。",
            ],
        )

    def test_digest_paper_falls_back_to_field_level_format_tightening_when_bulk_parse_fails(self) -> None:
        planner = Planner(FormatFieldFallbackDigestClient(), default_max_results=5)
        paper = Paper(
            paper_id="2604.20003",
            source_primary="arxiv",
            arxiv_id="2604.20003",
            versioned_id="2604.20003v1",
            title="Verifier-Guided Test-Time Scaling",
            abstract="We study verifier-guided test-time scaling.",
            authors=["Eve"],
            published="2026-04-10T00:00:00Z",
            updated="2026-04-11T00:00:00Z",
            entry_id="http://arxiv.org/abs/2604.20003v1",
            entry_url="http://arxiv.org/abs/2604.20003v1",
            pdf_url="http://arxiv.org/pdf/2604.20003v1",
            primary_category="cs.AI",
            categories=["cs.AI"],
        )
        extracted = ExtractedPaperContent(
            abstract="We study verifier-guided test-time scaling.",
            introduction="Verifier quality changes the value of larger candidate pools.",
            method="We compare candidate generation and reranking.",
            experiments="We evaluate math and code reasoning tasks.",
            conclusion="Future work studies calibrated verifiers.",
        )

        digest = planner.digest_paper("详细介绍这篇论文", paper, extracted, [])

        self.assertIn("\n\n1. **数据准备**", digest.method)
        self.assertEqual(digest.experiment_setup, "实验在数学与代码任务上进行，\n\n对比不同候选规模和验证策略。")
        self.assertEqual(digest.improvement_ideas, ["引入校准后的验证器。"])
