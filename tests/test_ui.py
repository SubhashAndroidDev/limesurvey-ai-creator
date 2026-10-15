import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import survey_creator.llm as llm
llm.time.sleep = lambda s: None
from survey_creator import service
from survey_creator.llm import GroqClient
from test_resilience import ChaoticChat
from streamlit.testing.v1 import AppTest

def fake_client(cfg):
    c = GroqClient("m", api_key="k", sleep=lambda s: None, tokens_per_minute=10**9)
    c._chat = ChaoticChat("chaos")
    return c
service.build_client = fake_client

cfg_patch = service.AppConfig
at = AppTest.from_file(str(Path(__file__).resolve().parent.parent / "app.py"), default_timeout=120)
at.run()
at.text_area(key="request_input").input("school feedback survey").run()
at.button[[b.label for b in at.button].index("✨ Generate survey")].click().run()
assert not at.exception, at.exception
survey = at.session_state["survey"]
qs = [q for _, q in survey.iter_questions()]
print("generated:", len(qs), "statuses:", {q.status for q in qs})

def btn(key): return at.button(key=key)

# 1) edit a question text + an answer
q1 = next(q for q in qs if q.type_key == "single_choice")
at.text_input(key=f"{q1.code}|text").input("Edited: how is the canteen food?").run()
at.text_input(key=f"{q1.code}|answers|0").input("Awful").run()
assert not at.exception
q1 = at.session_state["survey"].find_question(q1.code)[1]
print("edited text:", q1.text, "| first answer:", q1.answers[0], "| status:", q1.status)

# 2) delete an answer row (single choice has >3 answers) and add one back
n = len(q1.answers)
btn(f"{q1.code}|answers|0|del").click().run()
assert not at.exception
q1 = at.session_state["survey"].find_question(q1.code)[1]
print("answers", n, "->", len(q1.answers), "first now:", q1.answers[0])
btn(f"{q1.code}|answers|add").click().run()
q1 = at.session_state["survey"].find_question(q1.code)[1]
print("after add row:", len(q1.answers), "(last blank:", repr(q1.answers[-1]) + ")")

# 3) delete a whole question
before = at.session_state["survey"].question_count
code = qs[-1].code
btn(f"{code}|del").click().run()
assert not at.exception
print("delete question:", before, "->", at.session_state["survey"].question_count)

# 4) add blank question + AI question to group 0
at.button(key="g|0|addblank").click().run()
assert not at.exception
at.button(key="g|0|addai").click().run()
assert not at.exception
s = at.session_state["survey"]
print("after adds:", s.question_count, "codes:", [q.code for _, q in s.iter_questions()])
print("download buttons:", len(at.get("download_button")), "| exceptions:", len(at.exception))
