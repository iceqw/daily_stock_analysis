import json
import unittest
from types import SimpleNamespace

from src.services.ai_opinion_validator import (
    AIOpinionSafetyError,
    parse_ai_opinion_output_v2,
    validate_ai_opinion_output_v2,
)


def _base():
    return {"schema_version": "ai-opinion-output-v2", "summary": "s", "key_findings": [],
            "supporting_evidence": [], "risks": [], "uncertainties": [], "limitations": [],
            "things_to_watch": [], "investment_discipline_notes": [],
            "confidence": {"level": "medium", "rationale": "r"}, "disclaimer": "d",
            "principle_assessment": [], "overall_discipline_summary": "no principles"}


class OpinionV2ValidatorTest(unittest.TestCase):
    def _snapshot(self, *items):
        return SimpleNamespace(items=tuple(SimpleNamespace(principle_id=i, principle_version=v) for i, v in items))

    def _context(self):
        return SimpleNamespace(supporting_sources=[])

    def test_empty_snapshot_is_valid_and_deterministic(self):
        output = parse_ai_opinion_output_v2(json.dumps(_base()))
        validate_ai_opinion_output_v2(output, context=self._context(), principle_snapshot=self._snapshot())

    def test_exact_id_version_coverage_and_duplicate_rejection(self):
        payload = _base()
        assessment = {"principle_id": 1, "principle_version": 2, "status": "aligned", "relevance": 1,
                      "evidence": [], "explanation": "ok", "confidence": .8}
        payload["principle_assessment"] = [assessment]
        output = parse_ai_opinion_output_v2(json.dumps(payload))
        validate_ai_opinion_output_v2(output, context=self._context(), principle_snapshot=self._snapshot((1, 2)))
        payload["principle_assessment"].append(assessment)
        with self.assertRaises(AIOpinionSafetyError):
            validate_ai_opinion_output_v2(parse_ai_opinion_output_v2(json.dumps(payload)), context=self._context(), principle_snapshot=self._snapshot((1, 2)))

    def test_violated_requires_allowed_evidence(self):
        payload = _base()
        payload["principle_assessment"] = [{"principle_id": 1, "principle_version": 1, "status": "violated",
            "relevance": 1, "evidence": [], "explanation": "conflict", "confidence": .8}]
        with self.assertRaises(AIOpinionSafetyError):
            validate_ai_opinion_output_v2(parse_ai_opinion_output_v2(json.dumps(payload)), context=self._context(), principle_snapshot=self._snapshot((1, 1)))

    def test_transaction_language_is_rejected(self):
        payload = _base()
        payload["overall_discipline_summary"] = "buy now"
        with self.assertRaises(AIOpinionSafetyError):
            validate_ai_opinion_output_v2(parse_ai_opinion_output_v2(json.dumps(payload)), context=self._context(), principle_snapshot=self._snapshot())
