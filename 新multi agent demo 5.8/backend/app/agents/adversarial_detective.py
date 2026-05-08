from __future__ import annotations

import json
import os
import re

from app.agents.adv_detective_judge import run_adversarial_judge_rounds
from app.agents.homophone_candidates import build_phrase_homophone_candidates, should_participate_for_homophone
from app.agents.adv_variant_restorer import (
    VariantRestorer,
    adversarial_should_participate,
)
from app.core.agent_base import BaseAgent


PARTICIPATION_PROMPT = """你是对抗侦探（只负责对抗变体检测与还原）。

你只做两件事：
1) 检测文本是否存在对抗性变体（形近字/谐音/拼音替换/拆字/Unicode变异/特殊符号插入/零宽字符等）。
2) 如果存在，输出 will_participate=true，并给出 restored_text（还原后的纯文本）。

严格约束：
- 你不允许检索规则库/知识库
- 你不允许判断违规/正常
- will_participate=false 时，restored_text 置空字符串
- 只输出 JSON，不要解释

输出 JSON 格式:

{{
  "will_participate": true|false,
  "reason": "简要原因",
  "restored_text": "仅当 will_participate=true 时返回还原后的纯净文本，否则为空字符串"
}}

内容: {content}
"""


def _pipeline_mode() -> str:
    """llm｜deterministic｜llm_augment｜full（V2: 检索+初判+[复核]，输出违规/不确定/正常并进置信度票据）"""
    # 默认走 full，避免 llm 分支对返回 JSON 严格依赖导致“解析失败默认不参与”
    return (os.getenv("ADVERSARIAL_PIPELINE") or "full").strip().lower()


def _adv_category() -> str | None:
    c = (os.getenv("ADV_DETECTIVE_CATEGORY") or "").strip()
    return c or None


def _effective_adv_category(agent: "AdversarialDetective") -> str | None:
    if _adv_category():
        return _adv_category()
    if agent.audit_id:
        cfg = agent.blackboard.get_state(agent.audit_id, "config") or {}
        raw = agent.blackboard.get_state(agent.audit_id, "category") or cfg.get("category")
        if raw:
            return str(raw).strip()
    return None


class AdversarialDetective(BaseAgent):
    """对抗侦探：可选「规则引擎预处理 + LLM」，或仅用规则引擎以减少 LLM。"""

    _map = {
        "@": "a",
        "0": "o",
        "1": "i",
        "$": "s",
        "*": "",
        "！": "!",
    }

    def _normalize_legacy(self, content: str) -> str:
        normalized = content
        for src, dst in self._map.items():
            normalized = normalized.replace(src, dst)
        return normalized

    def restore_variants(self, text: str) -> str:
        """兜底还原：新版优先走 VariantRestorer。"""
        vr = VariantRestorer()
        restored, _ = vr.restore(text or "")
        s = restored.strip() or ""
        if not s:
            s = self._normalize_legacy(text or "")
            s = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", s)
            s = re.sub(r"[`~^|]+", "", s)
            s = re.sub(r"[ \t]+", " ", s).strip()
        return s

    def _homophone_prompt(self, text: str, restored: str) -> dict:
        """谐音弱处理：候选竞争 + 上下文支持。"""
        raw = text or ""
        # 同时捕获纯拉丁 token、夹杂中文的拼音 token，以及常见短缩写
        tokens = re.findall(r"(?<![a-zA-Z])([a-zA-Z]{2,10})(?![a-zA-Z])", raw)
        if not tokens:
            return {"participate": False, "confidence": 0.0, "reason": "无谐音候选", "candidates": []}
        all_candidates = []
        for tok in tokens:
            participate, score, reason, candidates = should_participate_for_homophone(tok, text)
            if candidates:
                all_candidates.append({"token": tok, "participate": participate, "score": score, "reason": reason, "candidates": candidates})
        if not all_candidates:
            return {"participate": False, "confidence": 0.0, "reason": "无谐音候选", "candidates": []}
        top = max(all_candidates, key=lambda x: float(x.get("score", 0.0) or 0.0))
        top_score = float(top.get("score", 0.0) or 0.0)
        strong_context = any(k in (text or "") for k in ["威胁", "攻击", "暴力", "杀", "死", "违规", "敏感", "煽动", "分裂", "对抗"])
        low_band = top_score <= 0.45 and not strong_context
        cap = 0.45 if low_band else 0.75
        participate = bool(top.get("participate", False)) and (strong_context or top_score >= 0.35)
        if len(top.get("candidates", [])) >= 2 and abs(float(top["candidates"][0]["score"]) - float(top["candidates"][1]["score"])) < 0.12:
            participate = False
        return {
            "participate": participate,
            "confidence": min(cap, max(0.15, top_score)),
            "reason": top.get("reason", "谐音弱语义推断"),
            "candidates": top.get("candidates", []),
            "token": top.get("token"),
            "strong_context": strong_context,
        }

    async def _execute_deterministic(self, content: str) -> dict:
        """确定性对抗检测：检测变体并还原，不做违规判决。"""
        r = VariantRestorer()
        await self.log("检测开始", "开始对抗性变体检测", {"pipeline": "deterministic"})
        if not adversarial_should_participate(r, content):
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "未发现对抗变体特征，或短文本跳过",
                "confidence": 1.0,
                "will_participate": False,
                "restored_text": "",
                "detection_details": {
                    "pipeline": "deterministic",
                    "transformations": [],
                    "risk_signals": [],
                },
            }
            await self.log("输出结果", "对抗侦探不参与（确定性特征未命中）", result)
            return result

        restored, txs = r.restore(content)
        if restored.strip() == (content or "").strip() and not txs:
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "未产生有效还原或变体类型",
                "confidence": 1.0,
                "will_participate": False,
                "restored_text": "",
                "detection_details": {"pipeline": "deterministic", "transformations": [], "risk_signals": []},
            }
            await self.log("输出结果", "对抗侦探不参与（还原无变化）", result)
            return result

        risk_signals = list(dict.fromkeys(txs))
        result = {
            "agent": self.name,
            "verdict": "participating",
            "reason": f"检测到变体迹象: {','.join(risk_signals) if risk_signals else '预处理还原'}",
            "confidence": 0.9,
            "will_participate": True,
            "restored_text": restored,
            "detection_details": {"pipeline": "deterministic", "transformations": txs, "risk_signals": risk_signals},
        }
        await self.log("参与判断", "确定性引擎判断参与还原", {"transformations": txs, "risk_signals": risk_signals})
        await self.log("变体还原", "已还原对抗性变体", {"original": content, "restored": restored, "risk_signals": risk_signals})
        await self.log("输出结果", "对抗侦探参与并输出还原文本", {**result, "restored_len": len(restored)})
        return result

    async def _execute_full_judge(self, content: str) -> dict:
        """全量对抗检测：变体识别 + 还原 + 审核判断。"""
        r = VariantRestorer()
        await self.log("检测开始", "开始 full 对抗检测", {"pipeline": "full"})
        if not adversarial_should_participate(r, content):
            out = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "未见对抗特征或短文本跳过（full 模式）",
                "confidence": 1.0,
                "will_participate": False,
                "restored_text": "",
                "adversarial_judgment": False,
                "skip_phase2_rule_reaudit": False,
                "detection_details": {"pipeline": "full", "adv_stage": "no_participation", "risk_signals": []},
            }
            await self.log("检测结果", "对抗侦探未发现变体特征", {"risk_signals": [], "will_participate": False, "restored_text": ""})
            await self.log("输出结果", "对抗侦探不参与（full）", out)
            return out

        restored, txs = r.restore(content)
        risk_signals = list(dict.fromkeys(txs))
        if restored.strip() == (content or "").strip() and not txs:
            out = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": "未发现有效还原（full）",
                "confidence": 1.0,
                "will_participate": False,
                "restored_text": "",
                "adversarial_judgment": False,
                "skip_phase2_rule_reaudit": False,
                "detection_details": {"pipeline": "full", "adv_stage": "no_effective_restore", "risk_signals": []},
            }
            await self.log("输出结果", "对抗侦探不参与（full，无有效还原）", out)
            return out

        homophone_info = self._homophone_prompt(content, restored)
        phrase_homophones = build_phrase_homophone_candidates(content, restored)
        if homophone_info.get("candidates"):
            await self.log(
                "谐音分析",
                "谐音候选竞争分析",
                {
                    "token": homophone_info.get("token"),
                    "participate": homophone_info.get("participate"),
                    "confidence": homophone_info.get("confidence"),
                    "reason": homophone_info.get("reason"),
                    "candidates": homophone_info.get("candidates", []),
                    "strong_context": homophone_info.get("strong_context"),
                },
            )
        if phrase_homophones:
            await self.log("汉字谐音分析", "汉字谐音规避表达识别", {"items": phrase_homophones})

        await self.log("检测结果", "对抗侦探识别到变体特征", {"risk_signals": risk_signals, "transformations": txs, "will_participate": True})
        await self.log("变体还原", "full 管线：预处理还原完毕", {"original_len": len(content), "transformations": txs, "risk_signals": risk_signals, "restored_text": restored})

        phrase_trigger = None
        phrase_candidates = None
        if phrase_homophones:
            best_phrase = phrase_homophones[0]
            phrase_trigger = best_phrase.get("phrase")
            phrase_candidates = best_phrase.get("candidates", [])
            if phrase_candidates:
                top_phrase_score = float(phrase_candidates[0].get("score", 0.0) or 0.0)
                phrase_context_ok = top_phrase_score >= 0.35 or any(k in restored for k in ["违规", "敏感", "威胁", "攻击", "杀", "死", "分裂", "煽动"])
                if phrase_context_ok:
                    homophone_info = {
                        **homophone_info,
                        "participate": True,
                        "confidence": min(0.75 if phrase_context_ok else 0.45, max(float(homophone_info.get("confidence", 0.0) or 0.0), top_phrase_score)),
                        "reason": f"汉字谐音规避表达: {phrase_trigger}",
                        "phrase_trigger": phrase_trigger,
                        "phrase_candidates": phrase_candidates,
                        "strong_context": phrase_context_ok,
                    }
                else:
                    homophone_info = {
                        **homophone_info,
                        "participate": False,
                        "confidence": min(0.45, max(float(homophone_info.get("confidence", 0.0) or 0.0), top_phrase_score)),
                        "reason": f"汉字谐音歧义过高: {phrase_trigger}",
                        "phrase_trigger": phrase_trigger,
                        "phrase_candidates": phrase_candidates,
                        "strong_context": False,
                    }

        if homophone_info.get("candidates") and not homophone_info.get("participate"):
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": f"谐音歧义过高：{homophone_info.get('reason')}",
                "confidence": float(min(0.45, homophone_info.get("confidence", 0.0) or 0.0)),
                "will_participate": False,
                "restored_text": "",
                "adversarial_judgment": False,
                "skip_phase2_rule_reaudit": False,
                "detection_details": {
                    "pipeline": "full_adv_rule_chain",
                    "transformations": txs,
                    "risk_signals": txs,
                    "homophone": homophone_info,
                    "phrase_homophones": phrase_homophones,
                    "restored_text": restored,
                },
            }
            await self.log("输出结果", "对抗侦探 full：谐音歧义过高，不参与", result)
            return result

        judged = await run_adversarial_judge_rounds(
            original=content,
            restored=restored,
            transformations=txs,
            rag_service=self.rag,
            llm=self.llm,
            category=_effective_adv_category(self),
        )
        vd = str(judged.get("verdict", "uncertain"))
        final_conf = float(judged.get("confidence", 0.5))
        meta = judged

        # 对抗侦探自身审核：共享同一套规则库/知识库，但由自身链路审，不再转交规则执行员
        if homophone_info.get("participate") or phrase_homophones:
            final_conf = min(final_conf, 0.75 if homophone_info.get("strong_context") else 0.45)
            if vd == "violation" and not homophone_info.get("strong_context"):
                vd = "uncertain"

        if homophone_info.get("participate") is False and phrase_homophones and phrase_homophones[0].get("candidates"):
            final_conf = min(final_conf, 0.45)

        await self.log(
            "对抗判定",
            "adv 自审完成",
            {
                "verdict": vd,
                "reason": judged.get("reason", ""),
                "confidence": final_conf,
                "homophone_participate": homophone_info.get("participate"),
                "phrase_participate": bool(phrase_homophones),
                "stage": judged.get("stage"),
            },
        )

        result = {
            "agent": self.name,
            "verdict": vd,
            "confidence": final_conf,
            "reason": judged.get("reason", "对抗侦探自审完成"),
            "will_participate": True,
            "restored_text": restored,
            "adversarial_judgment": True,
            "skip_phase2_rule_reaudit": False,
            "primary_verdict": judged.get("primary_verdict"),
            "secondary_verdict": judged.get("secondary_verdict"),
            "adv_stage": judged.get("stage", "self_judge"),
            "need_knowledge": bool(judged.get("need_knowledge", False)),
            "knowledge_used": bool(judged.get("knowledge_used", False)),
            "matched_rules": judged.get("matched_rules") or [],
            "detection_details": {
                "pipeline": "full_adv_self_judge",
                "transformations": txs,
                "retrieved_count": judged.get("retrieved_count", 0),
                "risk_signals": txs,
                "restored_text": restored,
                "homophone": homophone_info,
                "phrase_homophones": phrase_homophones,
                "bundle_meta": judged.get("bundle_meta", {}),
            },
        }
        await self.log("输出结果", "对抗侦探 full：自审完成", result)
        return result

    async def execute(self, content: str) -> dict:
        mode = _pipeline_mode()
        if mode in {"full", "full_v2", "retrieve_judge", "adv_judge"}:
            return await self._execute_full_judge(content)
        if mode in {"deterministic", "det", "restore_v2", "rules"}:
            return await self._execute_deterministic(content)

        user_prompt = PARTICIPATION_PROMPT.format(content=content)
        if mode in {"llm_augment", "augment"}:
            vr = VariantRestorer()
            hint_restored, hints = vr.restore(content)
            user_prompt = (
                "[预处理引擎参考——仅供参考，最终决定仍由你输出 JSON]\n"
                f"检测到变体类型线索: {json.dumps(hints, ensure_ascii=False)}\n"
                f"预处理还原文本:\n{hint_restored}\n---\n\n"
                + user_prompt
            )
            await self.log("预处理", "已对内容做规则级还原候选", {"hints": hints})

        llm_result = await self.llm.complete(
            system_prompt="你是对抗检测专家，仅返回JSON。",
            user_prompt=user_prompt,
            use_strong_model=False,
            return_trace=True,
        )
        raw = llm_result.get("output_text", "")
        llm_dialogue = llm_result.get("trace", {})
        p = self.parse_json_output(
            raw,
            {"will_participate": False, "reason": "解析失败，默认不参与"},
        )
        await self.log("参与判断", "判断是否需要参与审核", {**p, "llm_dialogue": llm_dialogue}, raw)
        will = bool(p.get("will_participate", False))
        if not will:
            result = {
                "agent": self.name,
                "verdict": "not_participate",
                "reason": p.get("reason", "未检测到对抗性变体"),
                "confidence": 1.0,
                "will_participate": False,
                "restored_text": "",
                "detection_details": {"pipeline": mode or "llm"},
            }
            await self.log("输出结果", "对抗侦探不参与", result)
            return result

        restored = str(p.get("restored_text") or "").strip() or self.restore_variants(content)
        det = {"pipeline": mode or "llm"}
        if mode in {"llm_augment", "augment"}:
            vr2 = VariantRestorer()
            _, h2 = vr2.restore(content)
            det["hints"] = h2

        await self.log("变体还原", "已还原对抗性变体", {"original": content, "restored": restored})
        result = {
            "agent": self.name,
            "verdict": "participating",
            "reason": p.get("reason", "检测到对抗性变体"),
            "confidence": 0.9,
            "will_participate": True,
            "restored_text": restored,
            "detection_details": det,
        }
        await self.log("输出结果", "对抗侦探参与并输出还原文本", {**result, "restored_len": len(restored)})
        return result
