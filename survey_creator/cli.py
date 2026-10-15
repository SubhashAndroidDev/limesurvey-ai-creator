"""Command line interface: ``python -m survey_creator.cli "hotel guest survey" -n 10 -o hotel.lss``."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from .config import AppConfig
from .service import build_client, generate_survey


def main(argv: list[str] | None = None) -> int:
    """Generate a survey from the terminal and save the .lss file."""
    parser = argparse.ArgumentParser(description="Generate a LimeSurvey .lss file with an LLM (Groq or a local Ollama model).")
    parser.add_argument("request", help="Describe the survey, e.g. 'customer satisfaction survey for a hotel'")
    parser.add_argument("-n", "--questions", type=int, default=10, help="number of questions")
    parser.add_argument("-g", "--per-group", default=None, help="questions per group: a number or 'auto'")
    parser.add_argument("-l", "--language", default=None, help="language code, e.g. en, hi")
    parser.add_argument("-t", "--types", nargs="*", default=None, help="allowed question type keys")
    parser.add_argument("-o", "--output", default="survey.lss", help="output file")
    args = parser.parse_args(argv)

    try:
        cfg = AppConfig.load()
        client = build_client(cfg)
        ok,message = client.ping()
    except (ValueError, RuntimeError) as exc:  # e.g. GROQ_API_KEY missing
        print(f"Configuration/connection error: {exc}")
        return 1
    
    print(message)
    if not ok:
        return 1

    def progress(stats, message):  # printed after every update of a stage
        if message:
            print(f"  {message}")

    try:
        result = generate_survey(args.request, args.questions, cfg=cfg, client=client, language=args.language,
                                 allowed_types=args.types, questions_per_group=args.per_group, on_event=progress)
    except (ValueError, RuntimeError) as exc:
        print(f"Could not generate the survey: {exc}")
        return 1
    Path(args.output).write_bytes(result.lss_bytes)
    print(f"Saved {args.output} ({result.total_tokens} tokens, {result.duration_s:.1f}s)")
    for issue in result.issues:
        print(f"  warning: {issue}")
    failed = [q.code for _, q in result.survey.iter_questions() if q.status == "failed"]
    if failed:
        print(f"  skipped failed questions: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
