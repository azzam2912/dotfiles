#!/usr/bin/env python3
"""Regression test for tex2sim.py camp/group payload shapes.

Run from the repo root:  python3 0-scripts/test_tex2sim.py
Drives the real CLI end to end with a sample paper in /tmp.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "0-scripts", "tex2sim.py")

SAMPLE = r"""
\documentclass{article}
\title{Sample Quiz}
\begin{document}
\section*{Section A: Multiple Choice (3 points each)}
\begin{enumerate}
% Answer: B (key step)
\item What is $1+1$?
\quad (A) 1 \quad (B) 2 \quad (C) 3
\end{enumerate}
\end{document}
"""


INSTR_SAMPLE = r"""
\documentclass{article}
\title{Quiz With Rules}
\begin{document}
\textbf{\Huge Quiz With Rules}\\
\textbf{Some Class, Someday}
\textbf{Instructions:}
Do your best and show your work.
\begin{enumerate}
\item No talking during the quiz.
\item Raise your hand if you finish early.
\end{enumerate}
\section*{Section A: Short Answer (1 points each)}
\begin{enumerate}
% Answer: 5
\item What is $2+3$?
\end{enumerate}
\end{document}
"""


def run_tex2sim(*argv, tex_body=SAMPLE):
    with tempfile.TemporaryDirectory() as d:
        tex = os.path.join(d, "sample.tex")
        out = os.path.join(d, "payload.json")
        with open(tex, "w") as f:
            f.write(tex_body)
        p = subprocess.run(
            [sys.executable, SCRIPT, tex, "-o", out, *argv],
            capture_output=True, text=True)
        payload = None
        if p.returncode == 0:
            with open(out) as f:
                payload = json.load(f)
        return p, payload


class TestPayloadShapes(unittest.TestCase):
    def test_camp_has_target_groups_and_no_dates(self):
        p, payload = run_tex2sim("--mode", "camp", "--camp-group", "84")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(payload["targetCampGroups"], [{"campGroupId": "84"}])
        self.assertNotIn("dueDate", payload)
        self.assertNotIn("releaseDate", payload)
        self.assertNotIn("groupAccess", payload)
        self.assertNotIn("targetGroups", payload)
        self.assertEqual(payload["maxScore"], 3)  # startingPoints + points

    def test_group_has_dates_and_group_access(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertNotIn("targetCampGroups", payload)
        self.assertNotIn("targetGroups", payload)
        self.assertEqual(payload["groupAccess"], [{"groupId": "34"}])
        self.assertEqual(payload["releaseDate"], "2026-09-25T06:00:00.000Z")
        self.assertEqual(payload["dueDate"], "2026-10-01T10:30:00.000Z")
        self.assertTrue(payload["isHidden"])
        self.assertFalse(payload["showScoreToStudents"])
        for key in ("deletedQuestionIds", "deletedPassageIds",
                    "deletedPartIds", "tutorAccess"):
            self.assertEqual(payload[key], [])
        q = payload["questions"][0]
        self.assertEqual(q["answerKey"], [{"optionIndex": 1}])
        for key in ("hasQuestionImage", "hasNewQuestionImage",
                    "hasAnswerImage", "hasNewAnswerImage"):
            self.assertFalse(q[key])

    def test_group_update_shape(self):
        # Updates PATCH .../<group>/<sim>/edit with the site's own shape:
        # empty groupAccess, placeholder dbIds listed for deletion.
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34", "--sim-id", "172",
            "--delete-question-ids", "8194",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("PATCH /api/tutor/group-simulations/34/172/edit", p.stderr)
        self.assertNotIn("targetGroups", payload)
        self.assertEqual(payload["groupAccess"], [])
        self.assertEqual(payload["deletedQuestionIds"], [8194])
        self.assertEqual(
            set(payload.keys()),
            {"title", "description", "instruction", "startingPoints",
             "maxScore", "dueDate", "showScoreToStudents", "sectionOrder",
             "releaseDate", "isHidden", "parts", "questions", "passages",
             "deletedQuestionIds", "deletedPassageIds", "deletedPartIds",
             "groupAccess", "tutorAccess"})

    def test_camp_update_shape(self):
        # Camp updates PATCH .../<camp-id>/<sim-id>/edit?campGroupId= with
        # additionalCampGroups and no targetCampGroups or dates.
        p, payload = run_tex2sim(
            "--mode", "camp", "--camp-group", "109", "--camp-id", "32",
            "--sim-id", "174", "--delete-question-ids", "8192",
            "--delete-part-ids", "849")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn(
            "PATCH /api/tutor/camp-simulations/32/174/edit?campGroupId=109",
            p.stderr)
        self.assertNotIn("targetCampGroups", payload)
        self.assertNotIn("releaseDate", payload)
        self.assertNotIn("dueDate", payload)
        self.assertEqual(payload["additionalCampGroups"], [])
        self.assertEqual(payload["deletedQuestionIds"], [8192])
        self.assertEqual(payload["deletedPartIds"], [849])
        self.assertEqual(
            set(payload.keys()),
            {"title", "description", "instruction", "startingPoints",
             "maxScore", "sectionOrder", "parts", "questions", "passages",
             "deletedQuestionIds", "deletedPassageIds", "deletedPartIds",
             "additionalCampGroups"})

    def test_camp_update_needs_camp_id(self):
        p, _ = run_tex2sim(
            "--mode", "camp", "--camp-group", "109", "--sim-id", "174")
        self.assertNotEqual(p.returncode, 0)

    def test_camp_update_needs_single_camp_group(self):
        p, _ = run_tex2sim(
            "--mode", "camp", "--camp-group", "109", "--camp-group", "110",
            "--camp-id", "32", "--sim-id", "174")
        self.assertNotEqual(p.returncode, 0)

    def test_delete_ids_need_sim_id(self):
        p, _ = run_tex2sim(
            "--mode", "camp", "--camp-group", "109",
            "--delete-question-ids", "8192")
        self.assertNotEqual(p.returncode, 0)

    def test_sim_id_needs_single_group(self):
        p, _ = run_tex2sim(
            "--mode", "group", "--group", "34", "--group", "35",
            "--sim-id", "172",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertNotEqual(p.returncode, 0)

    def test_group_default_instruction(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(payload["instruction"].startswith("Instruction\n1. No Timer"))
        self.assertIn("Calculator is NOT allowed", payload["instruction"])

    def test_tex_instructions_block_wins_over_default(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z",
            tex_body=INSTR_SAMPLE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("Do your best and show your work.", payload["instruction"])
        self.assertIn("1. No talking during the quiz.", payload["instruction"])
        self.assertIn("2. Raise your hand if you finish early.", payload["instruction"])
        self.assertNotIn("No Timer", payload["instruction"])
        self.assertEqual(len(payload["questions"]), 1)  # pre-section list is not a question

    def test_itemize_in_instructions_becomes_lettered(self):
        # The site cannot render \begin{itemize}, so a nested itemize stays
        # with its rule as a) b) lines and no \begin{...} reaches the payload.
        tex = r"""
\documentclass{article}
\title{Quiz}
\begin{document}
\textbf{Instructions:}
\begin{enumerate}
\item No timer. You can work on it until the deadline.
\item No cheating:
\begin{itemize}
\item You are not allowed to discuss the questions and solutions with friends.
\item You are not allowed to use any AI such as ChatGPT, Gemini, Claude, etc.
\end{itemize}
\item Calculator is NOT allowed.
\end{enumerate}
\section*{Section A: Short Answer (1 points each)}
\begin{enumerate}
% Answer: 5
\item What is $2+3$?
\end{enumerate}
\end{document}
"""
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z",
            tex_body=tex)
        self.assertEqual(p.returncode, 0, p.stderr)
        instr = payload["instruction"]
        self.assertIn("a) You are not allowed to discuss", instr)
        self.assertIn("b) You are not allowed to use any AI", instr)
        self.assertNotIn("\\begin", instr)
        self.assertNotIn("\\end", instr)
        self.assertNotIn("\\item", instr)
        # Outer numbering continues past the nested list, not through it.
        self.assertIn("3. Calculator is NOT allowed.", instr)

    def test_itemize_in_question_stem_becomes_lettered(self):
        tex = r"""
\documentclass{article}
\title{Sim}
\begin{document}
\section*{Section A: Short Answer (5 points each)}
\begin{enumerate}
% Answer: 5 (key step)
\item Which of these are prime?
\begin{itemize}
\item 4
\item 5
\end{itemize}
\end{enumerate}
\end{document}
"""
        p, payload = run_tex2sim("--mode", "camp", "--camp-group", "32",
                                 tex_body=tex)
        self.assertEqual(p.returncode, 0, p.stderr)
        q = payload["questions"][0]
        self.assertIn("a) 4", q["text"])
        self.assertIn("b) 5", q["text"])
        self.assertNotIn("\\begin", q["text"])
        self.assertNotIn("\\end", q["text"])
        self.assertNotIn("\\item", q["text"])
        self.assertEqual(q["answerKey"], [{"answer": "5"}])

    def test_explicit_instruction_wins_over_tex_block(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z",
            "--instruction", "Custom rules.",
            tex_body=INSTR_SAMPLE)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(payload["instruction"], "Custom rules.")

    def test_tikz_coordinates_are_not_options(self):
        tex = r"""
\documentclass{article}
\title{Sim}
\begin{document}
\section*{Section A: Multiple Choice (5 points each)}
\begin{enumerate}
% Answer: C (key step)
\item Pick the odd one out. The points are marked as in the diagram.
\begin{tikzpicture}[scale=0.8]
\coordinate (A) at (0,0);
\coordinate (B) at (1,0);
\coordinate (C) at (2,0);
\draw (A) -- (B) -- (C);
\end{tikzpicture}
\quad (A) 1 \quad (B) 2 \quad (C) 3
\end{enumerate}
\end{document}
"""
        p, payload = run_tex2sim("--mode", "camp", "--camp-group", "32",
                                 tex_body=tex)
        self.assertEqual(p.returncode, 0, p.stderr)
        q = payload["questions"][0]
        self.assertEqual(q["type"], "multiple_choice")
        self.assertEqual([o["text"] for o in q["options"]], ["1", "2", "3"])
        self.assertEqual(q["answerKey"], [{"optionIndex": 2}])

    def test_many_coordinate_marks_do_not_crash(self):
        tex = r"""
\documentclass{article}
\title{Sim}
\begin{document}
\section*{Section A: Short Answer (5 points each)}
\begin{enumerate}
% Answer: 48 (half of 96)
\item The area of rectangle $ABCD$ is $96$. $E$ is the midpoint of $AD$,
and $F$ is on $DC$. As in (A), find the shaded area.
\begin{tikzpicture}[scale=0.9]
\coordinate (A) at (0,4);
\coordinate (B) at (6,4);
\coordinate (C) at (6,0);
\coordinate (D) at (0,0);
\coordinate (E) at (0,2);
\coordinate (F) at (2,0);
\coordinate (G) at (3,1);
\coordinate (H) at (4,2);
\draw (A) -- (B) -- (C) -- (D) -- cycle;
\end{tikzpicture}
\end{enumerate}
\end{document}
"""
        p, payload = run_tex2sim("--mode", "camp", "--camp-group", "32",
                                 tex_body=tex)
        self.assertEqual(p.returncode, 0, p.stderr)
        q = payload["questions"][0]
        self.assertEqual(q["type"], "text")
        self.assertEqual(q["answerKey"], [{"answer": "48"}])

    def test_group_matches_website_key_shape(self):
        # The site 422s on unknown top-level keys with a misleading
        # "Release date is required." even when releaseDate is present,
        # so the group body must use the site's own key set exactly.
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(
            set(payload.keys()),
            {"title", "description", "instruction", "startingPoints",
             "maxScore", "dueDate", "showScoreToStudents", "sectionOrder",
             "releaseDate", "isHidden", "parts", "questions", "passages",
             "deletedQuestionIds", "deletedPassageIds", "deletedPartIds",
             "groupAccess", "tutorAccess"})

    def test_friendly_dates_convert_from_jakarta_time(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "13:00-25-09-2026",
            "--due-date", "17:30-01-10-2026")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(payload["releaseDate"], "2026-09-25T06:00:00.000Z")
        self.assertEqual(payload["dueDate"], "2026-10-01T10:30:00.000Z")

    def test_friendly_date_dot_separator(self):
        p, payload = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "19.00-25-09-2026",
            "--due-date", "19:00-25-09-2026")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(payload["releaseDate"], "2026-09-25T12:00:00.000Z")
        self.assertEqual(payload["dueDate"], "2026-09-25T12:00:00.000Z")

    def test_bad_date_rejected(self):
        p, _ = run_tex2sim(
            "--mode", "group", "--group", "34",
            "--release-date", "tomorrow",
            "--due-date", "17:30-01-10-2026")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("bad date", p.stderr)

    def test_group_needs_dates(self):
        p, _ = run_tex2sim("--mode", "group", "--group", "34")
        self.assertNotEqual(p.returncode, 0)

    def test_group_needs_group(self):
        p, _ = run_tex2sim(
            "--mode", "group",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("--group", p.stderr)

    def test_group_rejects_camp_group(self):
        p, _ = run_tex2sim(
            "--mode", "group", "--camp-group", "84",
            "--release-date", "2026-09-25T06:00:00.000Z",
            "--due-date", "2026-10-01T10:30:00.000Z")
        self.assertNotEqual(p.returncode, 0)

    def test_camp_needs_camp_group(self):
        p, _ = run_tex2sim("--mode", "camp")
        self.assertNotEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
