"""Streamlit UI: describe a survey -> groups appear -> questions arrive one by one -> edit / add /
delete while they arrive -> download .lss.

Run with:  streamlit run app.py
Everything (groups, questions, answers) comes from the user's prompt; nothing is hard-coded.

JSON DB: the survey is autosaved to data/surveys/<id>.json (see survey_creator/storage.py) and the id
is kept in the URL (?sid=...), so a refresh / restart restores it. Lines marked "[JSON DB]" are the
only parts that deal with that storage.
"""
from __future__ import annotations

from copy import deepcopy
import functools
import logging
import streamlit as st

from survey_creator import service, storage  # [JSON DB] `storage` = JSON file save/load helper
from survey_creator.config import AppConfig
from survey_creator.llm import FatalLLMError
from survey_creator.models import Group, Question, Survey
from survey_creator.validation import clean_options, question_problems
from survey_creator.intent import NotSurveyRequest

log = logging.getLogger("survey_creator.app")
st.set_page_config(page_title="Survey Creator", layout="wide")


@st.cache_resource
def get_cfg() -> AppConfig:
    return AppConfig.load()


cfg = get_cfg()
FRIENDLY_FAIL = "We couldn't finish that just now. Please try again in a moment."


def _safe(fn):
    """Button callbacks must never show a traceback: log the problem and carry on."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            log.exception("callback %s failed", fn.__name__)
    return wrapper


# ---------------------------------------------------------------------------- helpers
def _find(code: str) -> Question | None:
    found = st.session_state.survey.find_question(code)
    return found[1] if found else None


def _reset_widgets(code: str) -> None:
    """Forget widget values of one question so the widgets re-read the model."""
    for key in [k for k in st.session_state if str(k).startswith(f"{code}|")]:
        del st.session_state[key]


@_safe
def _delete_question(code: str) -> None:
    service.delete_question(st.session_state.survey, code)
    _reset_widgets(code)


@_safe
def _delete_option(code: str, kind: str, index: int, expected_len: int | None = None) -> None:
    q = _find(code)
    if q is None:
        return
    items = getattr(q, kind)
    if (expected_len is not None and len(items) != expected_len) or not 0 <= index < len(items):
        return
    values = [st.session_state.get(f"{code}|{kind}|{i}", items[i]) for i in range(len(items))]
    del values[index]
    setattr(q, kind, values)
    for i in range(len(items)):
        st.session_state.pop(f"{code}|{kind}|{i}", None)
    q.status = "edited"


@_safe
def _add_option(code: str, kind: str, expected_len: int | None = None, high: int | None = None) -> None:
    q = _find(code)
    if q is None:
        return
    items = getattr(q, kind)
    if (expected_len is not None and len(items) != expected_len) or (high is not None and len(items) >= high):
        return
    values = [st.session_state.get(f"{code}|{kind}|{i}", items[i]) for i in range(len(items))]
    setattr(q, kind, values + [""])
    q.status = "edited"


# -- groups
@_safe
def _delete_group(uid: str) -> None:
    survey: Survey = st.session_state.survey
    for group in list(survey.groups):
        if group.uid == uid:
            for q in group.questions:
                _reset_widgets(q.code)
            for key in [k for k in st.session_state if str(k).startswith(f"g|{uid}|")]:
                del st.session_state[key]
            survey.groups.remove(group)


@_safe
def _add_group() -> None:
    survey: Survey = st.session_state.survey
    pattern = str(cfg.get("survey.fallback_group_name", "Section {index}"))
    survey.groups.append(Group(name=pattern.format(index=len(survey.groups) + 1)))


# -- generation control
@_safe
def _stop_generation() -> None:
    """Stop writing; questions that were not written yet are removed (finished ones stay)."""
    for group in st.session_state.survey.groups:
        group.questions = [q for q in group.questions if q.status != "pending"]
    st.session_state.gen["active"] = False


@_safe
def _resume_generation() -> None:
    st.session_state.gen["active"] = True
    st.session_state.gen.pop("error", None)


def _option_labels(spec) -> dict[str, str]:
    if spec.needs_answers and spec.needs_subquestions:
        return {"answers": "Scale columns", "subquestions": "Rows (statements)"}
    if spec.needs_answers:
        return {"answers": "Answer choices"}
    return {"subquestions": "Text boxes" if spec.code == "Q" else "Options"}


def _ranges(spec) -> dict[str, tuple[int, int]]:
    return {"answers": (spec.answers_min, spec.answers_max), "subquestions": (spec.subq_min, spec.subq_max)}


def _exportable_copy(survey: Survey) -> Survey:
    """Copy of the survey with blank option rows removed (what will really be exported)."""
    copy = deepcopy(survey)
    for _, q in copy.iter_questions():
        spec = cfg.types[q.type_key]
        q.answers = clean_options(q.answers, spec.answers_max) if spec.needs_answers else []
        q.subquestions = clean_options(q.subquestions, spec.subq_max) if spec.needs_subquestions else []
        if question_problems(cfg, q):
            q.status = "failed"  # incomplete -> skipped from the file, the user is told why in the card
    return copy


def _hints(q: Question) -> list[str]:
    """Friendly reasons why a question is not yet exportable (blank option rows are ignored)."""
    if not q.text.strip():
        return []
    spec = cfg.types[q.type_key]
    probe = deepcopy(q)
    probe.answers = clean_options(q.answers, spec.answers_max) if spec.needs_answers else []
    probe.subquestions = clean_options(q.subquestions, spec.subq_max) if spec.needs_subquestions else []
    return question_problems(cfg, probe)


# ---------------------------------------------------------------------------- restore saved survey
# [JSON DB] 1/6 - on first load of a session: if the URL has ?sid=<id> and that JSON file exists,
# load the survey from disk into session_state (this is what survives a refresh / server restart).
@st.cache_resource
def _cleanup_once() -> bool:
    storage.cleanup(30)  # [JSON DB] remove saved surveys older than 30 days (once per server start)
    return True


_cleanup_once()
_sid = st.query_params.get("sid")  # [JSON DB] survey id travels in the URL
if "survey" not in st.session_state and storage.valid_id(_sid):
    _restored = storage.load(_sid, known_types=set(cfg.types))  # [JSON DB] read data/surveys/<sid>.json
    if _restored is not None:
        st.session_state.survey = _restored
        st.session_state.sid = _sid
        if any(q.status == "pending" for _, q in _restored.iter_questions()):
            # [JSON DB] generation was interrupted: show it paused; ctx is rebuilt when "Continue" is pressed
            st.session_state.gen = {"ctx": None, "active": False}


# ---------------------------------------------------------------------------- input form
st.title("Survey Creator")
st.caption("Describe your survey. Groups appear first, then questions arrive one by one - edit or delete them while the rest are written.")

with st.sidebar:
    st.header("Options")
    languages = cfg.get("languages", {"en": "English"})
    language = st.selectbox("Language", list(languages), format_func=lambda c: languages[c])
    total = st.number_input("Number of questions", int(cfg.get("survey.min_questions", 1)),
                            int(cfg.get("survey.max_questions", 60)), int(cfg.get("survey.default_questions", 10)))
    per_group = st.selectbox("Questions per group", ["auto", 1, 2, 3, 4, 5, 6], index=0)
    type_options = {s.key: s.label for s in cfg.enabled_types()}
    chosen_types = st.multiselect("Question types (empty = all)", list(type_options), format_func=type_options.get)
    if st.button("Start over", use_container_width=True):
        st.session_state.clear()
        st.query_params.clear()  # [JSON DB] 2/6 - forget the survey id in the URL (the file itself is kept)
        st.rerun()

request = st.text_area("What survey do you want?", height=110, key="request_input",
                       placeholder="e.g. Student satisfaction survey for a high school, covering teaching, facilities and wellbeing")

start_ok = False
if st.button("Generate survey", type="primary"):
    if not request.strip():
        st.warning("Please describe the survey first.")
    else:
        try:
            with st.spinner("Planning the survey groups..."):
                new_survey, new_ctx = service.start_generation(
                    request, int(total), cfg=cfg, client=service.build_client(cfg), language=language,
                    allowed_types=chosen_types or None, questions_per_group=per_group)
            for key in [k for k in st.session_state if "|" in str(k)]:
                del st.session_state[key]
            st.session_state.survey = new_survey
            st.session_state.gen = {"ctx": new_ctx, "active": True}
            # [JSON DB] 3/6 - a new survey gets an id, the id goes into the URL, and the plan is saved at once
            st.session_state.sid = storage.new_id()
            st.query_params["sid"] = st.session_state.sid
            storage.save(st.session_state.sid, new_survey)
            start_ok = True
        except NotSurveyRequest as exc:  # not a survey request: friendly hint, nothing is created or changed
            st.warning(str(exc))    
        except (ValueError, RuntimeError) as exc:  # missing key, bad input: messages written for users
            st.error(str(exc))
        except Exception:
            log.exception("planning failed")
            st.error(FRIENDLY_FAIL)
if start_ok:
    st.rerun()

# ---------------------------------------------------------------------------- preview / editor
survey: Survey | None = st.session_state.get("survey")
gen = st.session_state.get("gen")
if survey is not None:
    st.divider()
    st.subheader("Preview & edit")

    pending = [q for _, q in survey.iter_questions() if q.status == "pending"]
    active = bool(gen and gen["active"])
    current = pending[0] if (active and pending) else None
    all_q = survey.question_count
    done_q = all_q - len(pending)

    if gen and gen.get("error"):
        st.error(gen["error"])
    if pending:
        bar_col, btn_col = st.columns([0.8, 0.2])
        bar_col.progress(done_q / max(all_q, 1), text=f"{done_q} of {all_q} questions ready"
                         + (" - you can edit or delete any finished question while the rest are written" if active else " - paused"))
        if active:
            btn_col.button("⏹ Stop", on_click=_stop_generation, use_container_width=True)
        else:
            btn_col.button("▶ Continue", on_click=_resume_generation, use_container_width=True)

    with st.expander("Survey title and messages", expanded=False):
        survey.title = st.text_input("Title", survey.title, key="s|title")
        survey.welcome_text = st.text_area("Welcome text", survey.welcome_text, key="s|welcome")
        survey.end_text = st.text_area("End text", survey.end_text, key="s|end")

    limits = cfg.defaults.get("question", {})
    max_chars = int(limits.get("text_max_chars", 400))
    labels = cfg.defaults.get("mandatory_labels", {"Y": "Yes", "N": "No", "S": "Soft"})

    for gi, group in enumerate(survey.groups):
        uid = group.uid
        with st.container(border=True):
            # ---- group header (name + description + delete)
            st.caption(f"GROUP {gi + 1} · {len(group.questions)} question{'s' if len(group.questions) != 1 else ''}")
            name_col, del_col = st.columns([0.92, 0.08])
            group.name = name_col.text_input("Group name", group.name, key=f"g|{uid}|name", label_visibility="collapsed")
            del_col.button("🗑", key=f"g|{uid}|del", help="Delete this group and all its questions",
                           on_click=_delete_group, args=(uid,))
            group.description = st.text_input("Group description", group.description, key=f"g|{uid}|desc",
                                              placeholder="What this group covers (optional)",
                                              label_visibility="collapsed")

            # ---- questions of the group, one by one
            for q in list(group.questions):
                spec = cfg.types[q.type_key]

                if q.status == "pending":  # not written yet: show where it will appear
                    if q is current:
                        st.info(f"✍️ Writing **{q.code}** ({spec.label})...")
                    else:
                        st.caption(f"⏳ {q.code} · {spec.label} - waiting")
                    continue

                with st.container(border=True):
                    # preview (always visible)
                    flag = "  ✏️ edited" if q.status == "edited" else ""
                    st.markdown(f"**{q.code}** · {q.text or '*(no text yet - open Edit to write it)*'}")
                    meta = f"{spec.label} · {'Required' if q.mandatory == 'Y' else 'Optional'}{flag}"
                    summary = " · ".join(x for x in (q.answers + q.subquestions) if x.strip())
                    st.caption(meta + (f"  |  {summary[:160]}" if summary else ""))
                    if q.note:
                        st.caption(f"ℹ️ {q.note}")

                    # edit / delete
                    with st.expander(f"✏️ Edit / delete {q.code}"):
                        text = st.text_input("Question", q.text, key=f"{q.code}|text", max_chars=max_chars)
                        helptext = st.text_input("Help text (optional)", q.help, key=f"{q.code}|help")
                        mand = st.selectbox("Required?", list(labels), index=list(labels).index(q.mandatory)
                                            if q.mandatory in labels else 1, format_func=labels.get, key=f"{q.code}|mand")
                        if (text, helptext, mand) != (q.text, q.help, q.mandatory):
                            q.text, q.help, q.mandatory = text, helptext, mand
                            q.status = "edited"

                        for kind, title in _option_labels(spec).items():
                            low, high = _ranges(spec)[kind]
                            items = getattr(q, kind)
                            st.markdown(f"<small>{title} ({low}–{high})</small>", unsafe_allow_html=True)
                            for i in range(len(items)):
                                col, btn = st.columns([0.9, 0.1])
                                value = col.text_input(f"{title} {i + 1}", items[i], key=f"{q.code}|{kind}|{i}",
                                                       label_visibility="collapsed")
                                if value != items[i]:
                                    items[i] = value
                                    q.status = "edited"
                                btn.button("🗑", key=f"{q.code}|{kind}|{i}|del", help="Delete this row",
                                           disabled=len(items) <= low, on_click=_delete_option,
                                           args=(q.code, kind, i, len(items)))

                            st.button(f"➕ Add {title.lower().rstrip('s') if kind == 'answers' else 'row'}",
                                      key=f"{q.code}|{kind}|add", disabled=len(items) >= high,
                                      on_click=_add_option, args=(q.code, kind, len(items), high))

                        hints = _hints(q)
                        if not q.text.strip():
                            st.caption("✏️ Write the question text - empty questions are left out of the file.")
                        elif hints:
                            st.caption("✏️ " + "; ".join(hints) + " - this question is left out until fixed.")

                        act_regen, act_del = st.columns(2)
                        if act_regen.button("🔄 Regenerate with AI", key=f"{q.code}|regen", use_container_width=True):
                            with st.spinner(f"Rewriting {q.code}..."):
                                try:
                                    service.regenerate_question(survey, q.code, cfg=cfg)
                                except (ValueError, RuntimeError) as exc:
                                    st.error(str(exc))
                                except Exception:
                                    log.exception("regenerate failed")
                                    st.error(FRIENDLY_FAIL)
                            _reset_widgets(q.code)
                            st.rerun()
                        act_del.button("🗑 Delete question", key=f"{q.code}|del", use_container_width=True,
                                       on_click=_delete_question, args=(q.code,))

            # ---- add a question to this group
            add_type, add_ai, add_blank = st.columns([0.5, 0.25, 0.25])
            new_type = add_type.selectbox("New question type", list(type_options), format_func=type_options.get,
                                          key=f"g|{uid}|newtype", label_visibility="collapsed")
            if add_ai.button("➕ Add with AI", key=f"g|{uid}|addai", use_container_width=True):
                with st.spinner("Drafting a new question..."):
                    try:
                        service.add_question(survey, gi, new_type, cfg=cfg, client=service.build_client(cfg), use_ai=True)
                    except (ValueError, RuntimeError) as exc:
                        st.error(str(exc))
                    except Exception:
                        log.exception("add question failed")
                        st.error(FRIENDLY_FAIL)
                st.rerun()
            if add_blank.button("➕ Add blank", key=f"g|{uid}|addblank", use_container_width=True):
                new_q = service.add_question(survey, gi, new_type, cfg=cfg)
                spec = cfg.types[new_type]
                new_q.answers = [""] * spec.answers_min
                new_q.subquestions = [""] * spec.subq_min
                st.rerun()

    st.button("➕ Add group", on_click=_add_group)

    # ------------------------------------------------------------------------ export
    st.divider()
    ready = [q for _, q in _exportable_copy(survey).iter_questions() if q.exportable]
    st.write(f"**{len(ready)} of {survey.question_count}** questions are ready to export.")
    if ready:
        try:
            data, issues = service.render_lss(_exportable_copy(survey), cfg)
            st.download_button("⬇️ Download .lss", data, file_name="survey.lss", mime="application/xml", type="primary")
            if issues:
                st.caption("Some items need a look: " + "; ".join(issues[:3]))
        except Exception:
            log.exception("export failed")
            st.info("We couldn't build the file just now. Check the highlighted questions and try again.")
    else:
        st.info("Complete at least one question to enable the download.")

    # ------------------------------------------------------------------------ autosave to JSON
    # [JSON DB] 4/6 - every run reaches this point with the latest edits (typed text, deleted rows,
    # added questions/groups, newly written questions), so saving here keeps the JSON file current.
    # The file is rewritten only when something really changed (compared with the last saved text).
    _sid_now = st.session_state.get("sid")
    if _sid_now:
        _json = storage.to_json(survey)
        if st.session_state.get("_saved_json") != _json and storage.save(_sid_now, survey, text=_json):
            st.session_state["_saved_json"] = _json

    # ------------------------------------------------------------------------ write the next question
    # Runs LAST so everything above (groups + finished questions) is already on screen and editable.
    # One question per script run: any click the user makes is applied on the next run.
    if active:
        try:
            if gen["ctx"] is None:
                # [JSON DB] 5/6 - a restored survey has no AI client yet: create it now ("Continue" was pressed)
                gen["ctx"] = service.make_context(cfg)
            if service.fill_next_question(survey, gen["ctx"]) is None:
                gen["active"] = False
        except (ValueError, RuntimeError, FatalLLMError) as exc:  # e.g. missing / rejected API key
            gen["active"], gen["error"] = False, str(exc)
        except Exception:
            log.exception("question generation failed")
            gen["active"], gen["error"] = False, FRIENDLY_FAIL
        st.rerun()  # [JSON DB] 6/6 - the next run autosaves the question that was just written

