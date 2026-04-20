"""AgentWrite-style plan → write handbook orchestration (Phase 8)."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import re
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services import agentwrite_llm_cache as llm_cache
from app.services import rag as rag_service
from app.services.llm import LlmClient

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

_PLAN_HARDENING = (
    "\n\nEnsure the total word count across all paragraphs is at least 20,000 words "
    "and there are between 25 and 40 paragraphs.\n"
)

_EXPAND_PROMPT = """You are extending an existing handbook paragraph with additional depth, examples, and citations to uploaded sources.

## Existing paragraph (for context only — do NOT repeat any of it)
$PARA$

## Retrieval context (cite document titles inline when used)
$CONTEXT$

Write ONLY the additional sentences that should be appended to the existing paragraph. Add at least $TARGET$ new words. Match the existing paragraph's tone. Do not restate sentences that already appear above. Do not output labels such as "Paragraph", "Main Point:", "Word Count:", or bullet markers."""

OnEvent = Callable[[dict[str, Any]], bool | Awaitable[bool]]
RetrieveContext = Callable[[str], Awaitable[str]]


async def _default_retrieve_context(q: str) -> str:
    raw = await rag_service.query(q, mode="hybrid", only_need_context=True)
    return await _normalize_rag_output(raw)


@dataclass(frozen=True)
class Step:
    index: int
    main_point: str
    target_words: int
    raw_line: str


def _read_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8")


def _count_words(text: str) -> int:
    return len((text or "").split())


def _parse_plan_line(line: str) -> Step | None:
    raw = line.strip()
    if not raw.lower().startswith("paragraph"):
        return None
    head = re.match(
        r"Paragraph\s+(\d+)\s*-\s*Main Point:\s*(.+)",
        raw,
        re.IGNORECASE | re.DOTALL,
    )
    if not head:
        return None
    idx = int(head.group(1))
    rest = head.group(2).strip()
    sep = re.compile(r"\s+-\s*Word Count:\s*", re.IGNORECASE)
    m = list(sep.finditer(rest))
    if not m:
        return None
    last = m[-1]
    main_point = rest[: last.start()].strip()
    tail = rest[last.end() :].strip()
    num = re.match(r"(\d+)\s*(?:words?)?\.?\s*$", tail, re.IGNORECASE)
    if not num:
        return None
    try:
        words = int(num.group(1))
    except ValueError:
        return None
    return Step(index=idx, main_point=main_point, target_words=words, raw_line=raw)


def _post_process_paragraph(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(
        r"^\s*Paragraph\s+\d+\s*[-–:.]\s*",
        "",
        t,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    t = re.sub(
        r"^\s*Main Point:\s*", "", t, count=1, flags=re.IGNORECASE | re.MULTILINE
    )
    t = re.sub(
        r"^\s*Word Count:\s*.*$",
        "",
        t,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    t = re.sub(r"^\s*[-*•]\s+", "", t, count=1)
    return t.strip()


async def _normalize_rag_output(raw: str | AsyncIterator[str]) -> str:
    if isinstance(raw, str):
        return raw
    parts: list[str] = []
    async for piece in raw:
        parts.append(piece)
    return "".join(parts)


async def _emit(on_event: OnEvent | None, payload: dict[str, Any]) -> bool:
    if on_event is None:
        return True
    out = on_event(payload)
    if inspect.isawaitable(out):
        out = await out  # type: ignore[union-attr]
    return bool(out)


async def plan(instruction: str) -> list[Step]:
    """Call the LLM with ``plan.txt`` and parse ``Paragraph N - Main Point: …`` lines."""
    template = _read_prompt("plan.txt")
    prompt = template.replace("$INST$", instruction.strip()) + _PLAN_HARDENING
    model = get_settings().openrouter_chat_model
    cached_raw = llm_cache.try_read("plan", model, prompt)
    if cached_raw is not None:
        raw = cached_raw
    else:
        llm = LlmClient()
        raw = await llm.complete(prompt, max_tokens=4096, temperature=0.35)
        llm_cache.store("plan", raw, model, prompt)
    steps: list[Step] = []
    unparsed: list[str] = []
    for line in raw.splitlines():
        st = _parse_plan_line(line)
        if st:
            steps.append(st)
        elif line.strip():
            unparsed.append(line.strip())
    steps.sort(key=lambda s: s.index)
    if unparsed:
        logger.info(
            "plan: %d non-empty lines did not match the Paragraph format (sample: %r)",
            len(unparsed),
            unparsed[:3],
        )
    if len(steps) < 25:
        logger.warning(
            "plan returned only %s steps (<25); model may have ignored hardening",
            len(steps),
        )
    return steps


async def write_step(
    instruction: str,
    plan_text: str,
    written_text: str,
    step: Step,
    context: str,
) -> str:
    """Render ``write.txt`` (including ``$CONTEXT$``) and return one cleaned paragraph."""
    template = _read_prompt("write.txt")
    ctx = (context or "").strip() or "(No retrieved context.)"
    prompt = (
        template.replace("$INST$", instruction.strip())
        .replace("$PLAN$", plan_text.strip())
        .replace("$TEXT$", written_text.strip())
        .replace("$STEP$", step.raw_line.strip())
        .replace("$CONTEXT$", ctx)
    )
    llm = LlmClient()
    raw = await llm.complete(prompt, max_tokens=4096, temperature=0.45)
    return _post_process_paragraph(raw)


async def expand_paragraph(
    paragraph: str,
    context: str,
    target_words: int,
) -> str:
    """Ask the LLM to lengthen a paragraph using retrieval context."""
    prompt = (
        _EXPAND_PROMPT.replace("$PARA$", paragraph.strip())
        .replace("$CONTEXT$", (context or "").strip() or "(No context.)")
        .replace("$TARGET$", str(max(200, int(target_words))))
    )
    model = get_settings().openrouter_chat_model
    hit = llm_cache.try_read("expand", model, prompt)
    if hit is not None:
        return hit
    llm = LlmClient()
    raw = await llm.complete(prompt, max_tokens=4096, temperature=0.4)
    out = _post_process_paragraph(raw)
    llm_cache.store("expand", out, model, prompt)
    return out


def _partial_markdown(instruction: str, steps: list[Step], bodies: list[str]) -> str:
    if not bodies:
        return f"# {instruction.strip()[:200]}\n\n(Incomplete — no sections written yet.)\n"
    use_steps = steps[: len(bodies)]
    return _markdown_handbook(instruction, use_steps, bodies)


def _markdown_handbook(title: str, steps: list[Step], bodies: list[str]) -> str:
    if len(bodies) != len(steps):
        raise ValueError("bodies length must match steps")
    if not steps:
        return f"# {title.strip()[:200]}\n\n(No sections.)\n"
    lines: list[str] = [f"# {title.strip()[:200]}", "", "## Table of Contents", ""]
    for i, s in enumerate(steps, start=1):
        lines.append(f"{i}. {s.main_point}")
    lines.extend(["", "---", ""])
    for s, body in zip(steps, bodies, strict=True):
        lines.append(f"## {s.main_point}")
        lines.append("")
        lines.append(body.strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


async def generate_handbook(
    instruction: str,
    on_event: OnEvent | None = None,
    *,
    retrieve_context: RetrieveContext | None = None,
) -> str:
    """Plan → write all paragraphs (RAG per step) → optional expansion → markdown + TOC."""
    rc = retrieve_context or _default_retrieve_context
    steps = await plan(instruction)
    if not steps:
        raise RuntimeError("plan() produced no steps; cannot generate handbook")

    plan_text = "\n".join(s.raw_line for s in steps)
    target_sum = sum(s.target_words for s in steps)
    if not await _emit(
        on_event,
        {
            "type": "plan_ready",
            "total_steps": len(steps),
            "target_words_sum": target_sum,
        },
    ):
        logger.info("handbook generation cancelled before plan_ready consumed")
        return ""

    bodies: list[str] = []
    written_joined = ""

    for i, step in enumerate(steps):
        q = f"{instruction.strip()}\n{step.main_point}"
        try:
            ctx = await rc(q)
        except Exception:
            logger.exception("RAG query failed for step %s", step.index)
            ctx = ""

        para = await write_step(instruction, plan_text, written_joined, step, ctx)
        bodies.append(para)
        written_joined = "\n\n".join(bodies)
        w = _count_words(para)
        rt = _count_words(written_joined)
        if not await _emit(
            on_event,
            {
                "type": "paragraph",
                "index": i + 1,
                "total": len(steps),
                "text": para,
                "words": w,
                "running_total": rt,
            },
        ):
            logger.info("handbook generation stopped by on_event (paragraph event)")
            return _partial_markdown(instruction, steps, bodies)

    total = _count_words(written_joined)
    if total < 20_000:
        await _emit(
            on_event,
            {
                "type": "expanding",
                "current_words": total,
                "target_floor": 20_000,
                "target_cap": 30_000,
            },
        )
        iterations = 0
        while total < 20_000 and total < 30_000 and iterations < 60:
            iterations += 1
            if not bodies:
                break
            idx, smallest = min(
                enumerate(bodies),
                key=lambda ib: _count_words(ib[1]) if ib[1].strip() else 10**9,
            )
            if _count_words(smallest) == 0:
                break
            step = steps[idx]
            try:
                ctx = await rc(f"{instruction.strip()}\n{step.main_point}")
            except Exception:
                logger.exception("RAG failed during expansion")
                ctx = ""
            need = max(400, min(2500, (20_000 - total + 2) // 2))
            addition = await expand_paragraph(smallest, ctx, need)
            extended = (smallest.rstrip() + "\n\n" + addition.lstrip()).strip()
            bodies[idx] = extended
            written_joined = "\n\n".join(bodies)
            total = _count_words(written_joined)
            if not await _emit(
                on_event,
                {
                    "type": "paragraph",
                    "index": idx + 1,
                    "total": len(steps),
                    "text": extended,
                    "words": _count_words(extended),
                    "running_total": total,
                    "phase": "expand",
                },
            ):
                logger.info(
                    "handbook generation stopped by on_event (expand paragraph)"
                )
                break

    return _markdown_handbook(instruction, steps, bodies)


def _sync_print_plan(steps: list[Step]) -> None:
    for s in steps:
        print(s.raw_line)


async def _cli_plan(instruction: str) -> None:
    steps = await plan(instruction)
    _sync_print_plan(steps)
    meta = {
        "steps": len(steps),
        "target_words_sum": sum(s.target_words for s in steps),
    }
    print(f"\n# meta: {json.dumps(meta)}", file=sys.stderr)


async def _cli_write_step(
    instruction: str,
    plan_line: str,
) -> None:
    st = _parse_plan_line(plan_line)
    if st is None:
        raise SystemExit(f"Could not parse plan line: {plan_line!r}")
    plan_text = plan_line
    text = await write_step(instruction, plan_text, "", st, "")
    print(text)


async def _cli_generate(instruction: str) -> None:
    md = await generate_handbook(instruction, on_event=None)
    print(md, end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentWrite handbook utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="Print plan lines from LLM")
    p_plan.add_argument("instruction", type=str)

    p_ws = sub.add_parser("write-step", help="Run a single write step")
    p_ws.add_argument("--instruction", required=True)
    p_ws.add_argument("--plan-line", required=True)

    p_gen = sub.add_parser("generate", help="Full handbook markdown to stdout")
    p_gen.add_argument("instruction", type=str)

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.cmd == "plan":
        asyncio.run(_cli_plan(args.instruction))
    elif args.cmd == "write-step":
        asyncio.run(_cli_write_step(args.instruction, args.plan_line))
    elif args.cmd == "generate":
        asyncio.run(_cli_generate(args.instruction))
    else:
        parser.error("unknown command")


if __name__ == "__main__":
    main()
