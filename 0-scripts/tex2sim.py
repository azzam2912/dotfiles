#!/usr/bin/env python3
"""
tex2sim.py — convert a Star Generation simulation .tex file into the JSON payload
that POST /api/tutor/camp-simulations (camp mode) or
POST /api/tutor/group-simulations (group mode) expects.

Usage:
    # camp simulation: needs at least one --camp-group
    python3 tex2sim.py paper.tex -o payload.json \
        --mode camp --camp-group 84 --max-score 100 --starting-score 0
    # group (regular class) simulation: dates and --group are required.
    # Dates take HH:MM-DD-MM-YYYY (Jakarta time unless --timezone says
    # otherwise); full ISO-8601 also works. --group is the class id from
    # the page URL (.../classes/group/34); without it the site answers
    # 422 "At least one target group is required."
    python3 tex2sim.py paper.tex -o payload.json \
        --mode group --group 34 --release-date 13:00-25-09-2026 \
        --due-date 17:30-01-10-2026 --max-score 23 --starting-score 12

--mode can be omitted when it is unambiguous: passing --camp-group implies
camp mode, otherwise group mode is assumed (and then the two dates are
required).

Then open the simulation-create page in Chrome, open DevTools console,
paste upload.js, and run:  uploadSim(<paste payload.json contents>)

What it reads from the .tex
---------------------------
* \title{...}                      -> simulation title
* \section*{Section A: ... (3 points each)}
                                   -> one Part per section, pointsCorrect = 3
* \item inside the enumerate of a   -> one question each
  section (depth 1 only)
* "% Answer: C"  comment above an   -> answer key (letter for MCQ, raw text
  \item                               for short answer)
* "\quad (A) x \quad (B) y ..."     -> multiple-choice options
* \begin{itemize} inside a question    -> flattened to "a) ...", "b) ..." lines
  or the Instructions block              (the site cannot render the env, so no
                                         \begin{...} reaches the payload)

Questions containing tikzpicture / tabular / figure / fbox are still emitted,
but flagged in _warnings because the diagram must be uploaded as an image by
hand in the web UI.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta

MATH_HINTS = (
    "$", "\\[", "\\frac", "\\overline", "\\underbrace", "\\times", "\\clubsuit",
    "\\sqrt", "\\cdot", "^", "_", "\\text", "\\begin{align",
)
NEEDS_IMAGE = ("tikzpicture", "tabular", "\\begin{figure}", "\\fbox", "includegraphics")
LETTERS = "ABCDEFGH"


# ----------------------------------------------------------------- helpers
def strip_comments(text, keep=False):
    """Remove % comments (respecting \\%). Returns (clean, comments)."""
    clean, comments = [], []
    for line in text.split("\n"):
        pos, i = None, 0
        while i < len(line):
            if line[i] == "%" and (i == 0 or line[i - 1] != "\\"):
                pos = i
                break
            i += 1
        if pos is None:
            clean.append(line)
        else:
            clean.append(line[:pos])
            comments.append(line[pos + 1:].strip())
    return "\n".join(clean), comments


LIST_ENV_RE = re.compile(
    r"\\begin\{(itemize|enumerate)\*?\}(?:\[[^\]]*\])?([\s\S]*?)\\end\{\1\*?\}",
    flags=re.S)


def _flatten_envs(s):
    """Worker for flatten_list_envs: replace matched envs only, no fallback."""
    def repl(m):
        kind, body = m.group(1), m.group(2)
        body = _flatten_envs(body)  # innermost list first
        lines, n = [], 0
        for chunk in re.split(r"\\item\b(?:\[[^\]]*\])?", body):
            t = chunk.strip()
            if not t:
                continue
            n += 1
            if kind == "itemize":
                prefix = f"{chr(ord('a') + n - 1)}) " if n <= 26 else f"{n}) "
            else:
                prefix = f"{n}. "
            lines.append(f"{prefix}{t}")
        return "\n" + "\n".join(lines) + "\n" if lines else "\n"

    prev = None
    while prev != s:
        prev = s
        s = LIST_ENV_RE.sub(repl, s)
    return s


def flatten_list_envs(s):
    """Flatten itemize/enumerate blocks into plain lettered/numbered lines.

    The site renderer does not understand \\begin{itemize} etc., so a nested
    list inside a question stem or the Instructions block becomes plain text:
    itemize items turn into "a) ...", "b) ..." lines and nested enumerate
    items into "1. ...", "2. ..." lines, with the \\begin/\\end tags dropped.
    """
    s = _flatten_envs(s)
    # Safety net for unmatched tags: drop the tags so no \begin{...} reaches
    # the payload; a stray \item reads as a lettered sub-item.
    s = re.sub(r"\\begin\{(itemize|enumerate)\*?\}(?:\[[^\]]*\])?", "", s)
    s = re.sub(r"\\end\{(itemize|enumerate)\*?\}", "", s)
    s = re.sub(r"\\item\b(?:\[[^\]]*\])?", "a) ", s)
    return s


def split_enumerates(s):
    """Split text into ("text", prose) / ("enum", body) segments.

    One segment per top-level enumerate env, honouring nesting so an
    enumerate inside an enumerate does not end the outer body early.
    """
    segs, pos = [], 0
    while True:
        m = re.search(r"\\begin\{enumerate\*?\}(?:\[[^\]]*\])?", s[pos:])
        if not m:
            segs.append(("text", s[pos:]))
            return segs
        segs.append(("text", s[pos:pos + m.start()]))
        body_start = pos + m.end()
        depth, end = 1, None
        for t in re.finditer(r"\\begin\{enumerate\*?\}|\\end\{enumerate\*?\}",
                             s[body_start:]):
            if t.group(0).startswith("\\begin"):
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    end = body_start + t.start()
                    pos = body_start + t.end()
                    break
        if end is None:  # unterminated: take the rest as one list
            segs.append(("enum", s[body_start:]))
            return segs
        segs.append(("enum", s[body_start:end]))


def detex(s):
    """Turn LaTeX prose into something the site's renderer handles nicely."""
    s = flatten_list_envs(s)
    s = re.sub(r"\\\[(.+?)\\\]", lambda m: "$$" + m.group(1).strip() + "$$", s, flags=re.S)
    s = re.sub(r"\\\((.+?)\\\)", lambda m: "$" + m.group(1).strip() + "$", s, flags=re.S)
    s = re.sub(r"\\textbf\{(.+?)\}", r"**\1**", s)
    s = re.sub(r"\\textit\{(.+?)\}|\\emph\{(.+?)\}", lambda m: "*" + (m.group(1) or m.group(2)) + "*", s)
    s = re.sub(r"\\(quad|qquad|,|;|!)\b", " ", s)
    s = s.replace("\\ldots", "...").replace("\\dots", "...")
    s = s.replace("---", "\u2014").replace("--", "\u2013")
    s = re.sub(r"\\begin\{(figure|center)\}\[?[^\]]*\]?|\\end\{(figure|center)\}|\\centering", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n\s*\n\s*\n+", "\n\n", s)
    return s.strip()


def uses_latex(s):
    return any(h in s for h in MATH_HINTS)


DEFAULT_INSTRUCTION = (
    "Instruction\n"
    "1. No Timer, you can do it until before the deadline.\n"
    "2. No cheating: \n"
    "- You are not allowed to discuss the questions and solutions with friends\n"
    "- You are not allowed to use any AI such as ChatGPT, Gemini, Claude, etc.\n"
    "3. Calculator is NOT allowed.\n"
    "4. Discussing the questions with parents or other coaches is allowed, "
    "as long as the intention is for learning the way/working, not just "
    "asking for the final answer.\n"
    "5. Only submit once. If there are many attempts of submissions, only "
    "the first submission will be counted."
)


def instruction_text(chunk):
    """Turn an Instructions block into plain site text.

    Flat enumerate envs become "1. ...", "2. ..." lines; other prose is
    detexed as-is, in order. A nested itemize inside one rule stays with
    that rule as "a) ...", "b) ..." lines, since the site cannot render
    \\begin{itemize}.
    """
    clean, _ = strip_comments(chunk)
    out, n = [], 0
    for kind, val in split_enumerates(clean):
        if kind == "enum":
            # Depth-aware split: \item lines of a nested itemize belong to
            # the outer rule, not to the top-level numbering.
            for _, block in split_items(val):
                item = re.sub(r"^\\item\b(?:\[[^\]]*\])?", "", block, count=1)
                t = detex(item).strip()
                if t:
                    n += 1
                    out.append(f"{n}. {t}")
        else:
            t = detex(val).strip()
            if t:
                out.append(t)
    return "\n".join(out).strip() or None


def extract_instructions(doc):
    """Content after \\textbf{Instructions:} up to the first \\section.

    Returns None when the paper has no such block.
    """
    m = re.search(r"\\section\*?\{", doc)
    head = doc[:m.start()] if m else doc
    m2 = re.search(r"\\textbf\{Instructions?:\}?", head)
    if not m2:
        return None
    chunk = re.sub(r"^\s*:", "", head[m2.end():], count=1)
    return instruction_text(chunk)


FRIENDLY_DATE = re.compile(r"^(\d{1,2})[:.](\d{2})-(\d{1,2})-(\d{1,2})-(\d{4})$")
TZ_OFFSET = re.compile(r"^([+-])(\d{1,2})(?::?(\d{2}))?$")


def parse_tz_offset(value):
    """Parse 'Z' or '+HH:MM' into a timedelta. Anything else is an error."""
    v = value.strip().upper()
    if v in ("Z", "UTC", "+00", "+00:00", "+0000"):
        return timedelta(0)
    m = TZ_OFFSET.match(value.strip())
    if not m:
        raise ValueError(f"bad --timezone {value!r}: want Z or +HH:MM")
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3) or 0)
    if hh > 14 or mm > 59:
        raise ValueError(f"bad --timezone {value!r}: want Z or +HH:MM")
    off = timedelta(hours=hh, minutes=mm)
    return -off if sign == "-" else off


def parse_moment(value, tz_offset):
    """Accept 'HH:MM-DD-MM-YYYY' (a dot also works: '19.00-25-09-2026')
    and return ISO-8601 UTC like the site sends ('...T....000Z').

    Full ISO-8601 ('2026-09-25T06:00:00.000Z') is passed through untouched.
    Anything else is an error.
    """
    v = value.strip()
    m = FRIENDLY_DATE.match(v)
    if not m:
        if "T" in v or re.match(r"^\d{4}-\d{1,2}-\d{1,2}", v):
            return v
        raise ValueError(f"bad date {value!r}: want HH:MM-DD-MM-YYYY or ISO-8601")
    hh, mm, dd, mo, yy = map(int, m.groups())
    try:
        local = datetime(yy, mo, dd, hh, mm)
    except ValueError:
        raise ValueError(f"bad date {value!r}: want HH:MM-DD-MM-YYYY")
    return (local - tz_offset).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def split_items(body):
    """Split an enumerate body into depth-1 \\item blocks."""
    tokens = list(re.finditer(r"\\begin\{(\w+\*?)\}|\\end\{(\w+\*?)\}|\\item\b", body))
    depth, starts = 0, []
    for t in tokens:
        if t.group(1):
            depth += 1
        elif t.group(2):
            depth -= 1
        elif depth == 0:
            starts.append(t.start())
    blocks = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(body)
        # comment lines sitting directly above this \item belong to it
        lead = []
        for line in reversed(body[:s].split("\n")):
            t = line.strip()
            if t.startswith("%"):
                lead.insert(0, t[1:].strip())
            elif t == "":
                continue
            else:
                break
        blocks.append((lead, body[s:e]))
    return blocks


def find_enumerate(section_body):
    """Return the body of the first top-level enumerate in a section."""
    m = re.search(r"\\begin\{enumerate\}(\[[^\]]*\])?", section_body)
    if not m:
        return None
    i, depth = m.end(), 1
    for t in re.finditer(r"\\begin\{enumerate\}|\\end\{enumerate\}", section_body[i:]):
        depth += 1 if t.group(0).startswith("\\begin") else -1
        if depth == 0:
            return section_body[i:i + t.start()]
    return section_body[i:]


def parse_options(clean):
    """Pull '\\quad (A) 59 \\quad (B) 61 ...' out of a question body.

    Marks inside tikzpicture/figure blocks are diagram code (e.g.
    \\coordinate (A)), not options, so they are ignored.
    """
    spans = [m.span() for m in re.finditer(
        r"\\begin\{(tikzpicture|figure)\}[\s\S]*?\\end\{\1\}", clean)]
    marks = [m for m in re.finditer(r"\(([A-H])\)\s*", clean)
             if not any(a <= m.start() < b for a, b in spans)]
    marks = [m for i, m in enumerate(marks)
             if i < len(LETTERS) and m.group(1) == LETTERS[i]] or marks
    if len(marks) < 2:
        return clean, []
    # options must be sequential A, B, C...
    seq = []
    for m in marks:
        if len(seq) < len(LETTERS) and m.group(1) == LETTERS[len(seq)]:
            seq.append(m)
    if len(seq) < 2:
        return clean, []
    opts = []
    for i, m in enumerate(seq):
        end = seq[i + 1].start() if i + 1 < len(seq) else len(clean)
        txt = clean[m.end():end]
        txt = re.sub(r"\\quad\s*$", "", txt.strip()).strip()
        opts.append(txt)
    stem = clean[:seq[0].start()]
    stem = re.sub(r"\\quad\s*$", "", stem.strip())
    return stem, opts


# ----------------------------------------------------------------- main parse
def parse_tex(src, skip_sections=("instruction", "answer key")):
    title_m = re.search(r"\\title\{(.+?)\}", src, flags=re.S)
    src = src.split("\\begin{document}", 1)[-1].split("\\end{document}", 1)[0]

    title = detex(title_m.group(1)) if title_m else "Simulation"
    instructions = extract_instructions(src)

    sections = list(re.finditer(r"\\section\*?\{(.+?)\}", src, flags=re.S))
    parts, questions, warnings = [], [], []
    part_no, q_index = 0, 0

    for si, sm in enumerate(sections):
        head = re.sub(r"\s+", " ", sm.group(1)).strip()
        if any(k in head.lower() for k in skip_sections):
            continue
        end = sections[si + 1].start() if si + 1 < len(sections) else len(src)
        body = src[sm.end():end]
        enum_body = find_enumerate(body)
        if not enum_body:
            continue

        pts = re.search(r"\((\d+)\s*points?\s*each\)", head)
        pc = int(pts.group(1)) if pts else 1
        part_no += 1
        part_id = f"p{part_no}"
        part_title = re.sub(r"\s*\(\d+\s*points?\s*each\)\s*", "", head).strip()
        parts.append({
            "tempId": part_id,
            "title": part_title,
            "description": "",
            "orderIndex": part_no,
            "pointsCorrect": pc,
            "pointsIncorrect": 0,
            "pointsUnanswered": 0,
        })

        for lead, block in split_items(enum_body):
            raw = block[len("\\item"):]
            clean, own = strip_comments(raw)
            answer = None
            for group in (lead, own):          # comments above the \item win
                for c in group:
                    am = re.match(r"answer\s*[:=]\s*(.+)", c, flags=re.I)
                    if am:
                        answer = am.group(1).split("(")[0].strip()
                if answer:
                    break
            stem_raw, opts_raw = parse_options(clean)
            stem = detex(stem_raw)
            if not stem:
                continue
            q_index += 1
            options = [
                {"text": detex(o), "useLatex": uses_latex(o), "orderIndex": i}
                for i, o in enumerate(opts_raw)
            ]
            if options:
                qtype = "multiple_choice"
                if answer and answer.upper() in LETTERS[:len(options)]:
                    key = [{"optionIndex": LETTERS.index(answer.upper())}]
                else:
                    key = []
                    warnings.append(f"Q{q_index}: no usable '% Answer: <letter>' comment")
            else:
                qtype = "text"
                key = [{"answer": answer}] if answer else []
                if not answer:
                    warnings.append(f"Q{q_index}: no usable '% Answer: <value>' comment")

            if any(n in raw for n in NEEDS_IMAGE):
                warnings.append(f"Q{q_index}: contains a diagram/table — upload an image by hand")

            questions.append({
                "tempId": f"q{q_index}",
                "tempPartId": part_id,
                "type": qtype,
                "text": stem,
                "useLatex": uses_latex(stem_raw),
                "orderIndex": q_index - 1,
                "pointsCorrect": pc,
                "pointsIncorrect": 0,
                "pointsUnanswered": 0,
                "options": options,
                "answerKey": key,
                "questionImagePath": None,
                "questionImageMimeType": None,
                "answerImagePath": None,
                "answerImageMimeType": None,
            })

    return title, instructions, parts, questions, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("texfile")
    ap.add_argument("-o", "--out", default="0-scripts/payload.json")
    ap.add_argument("--mode", choices=("camp", "group"), default=None,
                    help="camp posts to /api/tutor/camp-simulations with "
                         "targetCampGroups; group posts to "
                         "/api/tutor/group-simulations with due/release dates. "
                         "Defaults to camp when --camp-group is given, else group.")
    ap.add_argument("--camp-group", action="append", default=[],
                    help="camp group id (repeat for several); camp mode only")
    ap.add_argument("--group", action="append", default=[],
                    help="group class id from the page URL (.../classes/group/34, "
                         "so --group 34); repeat for several; group mode only")
    ap.add_argument("--release-date", default=None,
                    help="release date as HH:MM-DD-MM-YYYY (e.g. 13:00-25-09-2026) "
                         "or full ISO-8601; required in group mode, optional in camp mode")
    ap.add_argument("--due-date", default=None,
                    help="due date, same format as --release-date; "
                         "required in group mode, optional in camp mode")
    ap.add_argument("--timezone", default="+07:00",
                    help="which zone HH:MM-DD-MM-YYYY is written in "
                         "(default +07:00 Jakarta); full ISO-8601 dates ignore this")
    ap.add_argument("--hidden", dest="hidden", action="store_true", default=None,
                    help="mark the simulation hidden (default in group mode)")
    ap.add_argument("--visible", dest="hidden", action="store_false",
                    help="mark the simulation visible")
    ap.add_argument("--show-score", dest="show_score", action="store_true", default=None,
                    help="show the score to students")
    ap.add_argument("--hide-score", dest="show_score", action="store_false",
                    help="hide the score from students (default in group mode)")
    ap.add_argument("--points-incorrect", type=int, default=0,
                    help="points for a wrong answer on every question (default 0)")
    ap.add_argument("--sim-id", default=None,
                    help="update an existing simulation instead of creating: emits "
                         "the site's update shape and the upload goes to the "
                         ".../<id>/edit PATCH URL. Combine with "
                         "--delete-question-ids / --delete-part-ids to drop the "
                         "old content.")
    ap.add_argument("--camp-id", default=None,
                    help="camp id for the update URL path (camp mode with --sim-id: "
                         "PATCH .../camp-simulations/<camp-id>/<sim-id>/edit)")
    ap.add_argument("--delete-question-ids", default="",
                    help="comma-separated db ids of existing questions to delete on "
                         "update (the dbId values in the site's editor payload)")
    ap.add_argument("--delete-part-ids", default="",
                    help="comma-separated db ids of existing parts to delete on "
                         "update (the dbId values in the site's editor payload)")
    ap.add_argument("--title")
    ap.add_argument("--description", default="")
    ap.add_argument("--instruction", default=None,
                    help="instruction text; overrides the paper's "
                         "\\textbf{Instructions:} block and the built-in default")
    ap.add_argument("--starting-score", type=int, default=0)
    ap.add_argument("--max-score", type=int, default=None,
                    help="defaults to the sum of all question points")
    args = ap.parse_args()

    mode = args.mode or ("camp" if args.camp_group else "group")
    if mode == "camp" and not args.camp_group:
        ap.error("camp mode needs at least one --camp-group <id>")
    if mode == "camp" and args.group:
        ap.error("--group is group-only; drop it in camp mode")
    if mode == "group" and args.camp_group:
        ap.error("--camp-group is camp-only; drop it in group mode")
    if mode == "group" and not args.group:
        ap.error("group mode needs at least one --group <id> "
                 "(the site answers 422 without it)")
    if mode == "group" and not (args.release_date and args.due_date):
        ap.error("group mode needs both --release-date and --due-date")
    if args.sim_id and mode == "group" and len(args.group) != 1:
        ap.error("--sim-id needs exactly one --group <id>")
    if args.sim_id and mode == "camp" and not args.camp_id:
        ap.error("--sim-id in camp mode needs --camp-id <id>")
    if args.sim_id and mode == "camp" and len(args.camp_group) != 1:
        ap.error("--sim-id in camp mode needs exactly one --camp-group <id>")
    if args.camp_id and not args.sim_id:
        ap.error("--camp-id needs --sim-id")
    if args.delete_question_ids and not args.sim_id:
        ap.error("--delete-question-ids needs --sim-id")
    if args.delete_part_ids and not args.sim_id:
        ap.error("--delete-part-ids needs --sim-id")

    try:
        tz_offset = parse_tz_offset(args.timezone)
        release_date = parse_moment(args.release_date, tz_offset) if args.release_date else None
        due_date = parse_moment(args.due_date, tz_offset) if args.due_date else None
    except ValueError as e:
        ap.error(str(e))

    src = open(args.texfile, encoding="utf-8").read()
    title, tex_instructions, parts, questions, warnings = parse_tex(src)
    instruction = args.instruction or tex_instructions or DEFAULT_INSTRUCTION

    for p in parts:
        p["pointsIncorrect"] = args.points_incorrect
    for q in questions:
        q["pointsIncorrect"] = args.points_incorrect

    total = sum(q["pointsCorrect"] for q in questions)
    max_score = (args.max_score if args.max_score is not None
                 else args.starting_score + total)
    hidden = args.hidden if args.hidden is not None else True
    show_score = args.show_score if args.show_score is not None else False

    def db_ids(raw):
        return [int(x) if x.isdigit() else x
                for x in (s.strip() for s in raw.split(",")) if x]

    if mode == "camp":
        if args.sim_id:
            # Update: the site PATCHes .../<camp-id>/<sim-id>/edit?campGroupId=
            # with no targetCampGroups and no dates, exactly like its editor.
            payload = {
                "title": args.title or title,
                "description": args.description or (args.title or title)[:100],
                "instruction": instruction,
                "startingPoints": args.starting_score,
                "maxScore": max_score,
                "sectionOrder": ["standalone"] + [p["tempId"] for p in parts],
                "parts": parts,
                "questions": questions,
                "passages": [],
                "deletedQuestionIds": db_ids(args.delete_question_ids),
                "deletedPassageIds": [],
                "deletedPartIds": db_ids(args.delete_part_ids),
                "additionalCampGroups": [],
            }
        else:
            payload = {
                "title": args.title or title,
                "description": args.description or (args.title or title)[:100],
                "instruction": instruction,
                "startingPoints": args.starting_score,
                "maxScore": max_score,
                "sectionOrder": ["standalone"] + [p["tempId"] for p in parts],
                "parts": parts,
                "questions": questions,
                "passages": [],
                "targetCampGroups": [{"campGroupId": str(g)} for g in args.camp_group],
            }
            if release_date or due_date:
                payload["releaseDate"] = release_date
                payload["dueDate"] = due_date
            if args.hidden is not None:
                payload["isHidden"] = hidden
            if args.show_score is not None:
                payload["showScoreToStudents"] = show_score
    else:
        for q in questions:
            q["hasQuestionImage"] = False
            q["hasNewQuestionImage"] = False
            q["hasAnswerImage"] = False
            q["hasNewAnswerImage"] = False
        payload = {
            "title": args.title or title,
            "description": args.description or (args.title or title)[:100],
            "instruction": instruction,
            "startingPoints": args.starting_score,
            "maxScore": max_score,
            "dueDate": due_date,
            "showScoreToStudents": show_score,
            "sectionOrder": ["standalone"] + [p["tempId"] for p in parts],
            "releaseDate": release_date,
            "isHidden": hidden,
            "parts": parts,
            "questions": questions,
            "passages": [],
            "deletedQuestionIds": db_ids(args.delete_question_ids),
            "deletedPassageIds": [],
            "deletedPartIds": db_ids(args.delete_part_ids),
            # Create: target the group via groupAccess. Update (--sim-id):
            # the site PATCHes .../group-simulations/<group>/<sim>/edit with
            # an empty groupAccess, exactly like its own editor does.
            "groupAccess": [] if args.sim_id else
                           [{"groupId": str(g)} for g in args.group],
            "tutorAccess": [],
        }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"mode {mode}: {len(parts)} parts, {len(questions)} questions, "
          f"total points {total}", file=sys.stderr)
    if release_date or due_date:
        print(f"releaseDate {release_date}  dueDate {due_date}", file=sys.stderr)
    print(f"maxScore set to {payload['maxScore']} (must equal startingPoints + total or the site blocks publish)",
          file=sys.stderr)
    for w in warnings:
        print("  ! " + w, file=sys.stderr)
    if args.sim_id and mode == "group":
        gid = str(args.group[0])
        print(f"update: PATCH /api/tutor/group-simulations/{gid}/{args.sim_id}/edit",
              file=sys.stderr)
        print(f'upload with: await uploadSim(PAYLOAD, {{simId: {args.sim_id}, groupId: "{gid}"}})',
              file=sys.stderr)
    if args.sim_id and mode == "camp":
        cid, gid = str(args.camp_id), str(args.camp_group[0])
        print(f"update: PATCH /api/tutor/camp-simulations/{cid}/{args.sim_id}/edit?campGroupId={gid}",
              file=sys.stderr)
        print(f'upload with: await uploadSim(PAYLOAD, {{simId: {args.sim_id}, campId: {cid}, campGroupId: "{gid}"}})',
              file=sys.stderr)
    print(f"written to {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()