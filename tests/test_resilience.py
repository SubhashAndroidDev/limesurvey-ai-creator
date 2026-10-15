"""Simulates the real Groq failures: 429s, wrong JSON keys, garbage, bad API key."""
import json, sys, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import survey_creator.llm as llm
from survey_creator.config import AppConfig
from survey_creator.llm import GroqClient
from survey_creator.service import generate_survey, add_question, delete_question, render_lss
from survey_creator.models import Survey

llm.time.sleep = lambda s: None  # do not really wait in tests


class Msg:
    def __init__(self, content, tokens=900):
        self.content, self.usage_metadata = content, {"total_tokens": tokens}


class RateLimitError(Exception):
    pass


class ChaoticChat:
    """Behaves like the broken Groq runs from the screenshot."""

    def __init__(self, mode):
        self.mode, self.calls, self.n429 = mode, 0, 0

    def invoke(self, prompt, response_format=None):
        self.calls += 1
        if self.mode == "badkey":
            raise Exception("Error code: 401 - Invalid API Key")
        if "mode429" in self.mode and self.calls % 3 == 0 and self.n429 < 6:
            self.n429 += 1
            raise RateLimitError("Error code: 429 - Rate limit reached ... Please try again in 2.76s.")
        if "Design the survey skeleton" in prompt:
            return Msg(json.dumps({"survey_title": "School Feedback", "sections": ["Teaching", "Facilities"]}))
        if "Write exactly ONE question" in prompt:
            if "Multiple short text" in prompt and self.mode != "ok":
                return Msg(json.dumps({"name": "x"}))            # unrecoverable -> must fall back
            if "Array (matrix)" in prompt and self.mode != "ok":
                return Msg("not json at all")                   # unrecoverable -> must fall back
            return Msg(json.dumps({"question": f"How satisfied are you with aspect number {self.calls} of the school?",
                                   "items": ["a", "b"], "help": ""}))  # wrong key 'question' -> repaired
        if "Fill these JSON fields" in prompt:
            return Msg(json.dumps({"options": ["Very poor", "Poor", "Good", "Very good"],
                                   "rows": [{"label": "Clarity"}, {"label": "Pace"}, {"label": "Support"}]}))
        return Msg("{}")


def run(mode, n=10):
    cfg = AppConfig.load()
    cfg.settings["llm"]["heal_cooldown_seconds"] = 0
    client = GroqClient("m", api_key="k", sleep=lambda s: None, tokens_per_minute=10**9)
    client._chat = ChaoticChat(mode)
    res = generate_survey("school feedback survey", n, cfg=cfg, client=client, questions_per_group=3)
    return cfg, res, client


for mode in ("ok", "chaos", "chaos+mode429"):
    cfg, res, client = run(mode)
    qs = [q for _, q in res.survey.iter_questions()]
    auto = [q.code for q in qs if q.note]
    assert all(q.status == "ok" for q in qs), [(q.code, q.status) for q in qs]
    assert res.issues == [], res.issues
    print(f"{mode:15} questions={len(qs)} all_ok=True lss_valid=True auto_drafted={auto} llm_calls={client._chat.calls}")

# bad key -> one clear, friendly error (the only case that is surfaced)
try:
    run("badkey")
except RuntimeError as e:
    print("badkey ->", e)

# add / delete / export
cfg, res, _ = run("ok")
s = res.survey
before = s.question_count
q = add_question(s, 0, "single_choice", cfg=cfg)           # blank
q.text, q.answers = "Do you like the new timetable?", ["Yes", "No", "Not sure"]
delete_question(s, s.groups[0].questions[0].code)
data, issues = render_lss(s, cfg)
print("after add+delete:", before, "->", s.question_count, "issues:", issues, "new code:", q.code)
