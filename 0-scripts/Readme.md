# Bulk-loading simulation questions from a .tex file

Two pieces:

* `tex2sim.py` — reads your paper `.tex`, writes `payload.json`.
  Two modes: `camp` and `group` (regular class).
* `upload.js` — pasted into the Chrome DevTools console, POSTs that payload to
  `/api/tutor/camp-simulations` or `/api/tutor/group-simulations`
  (the same endpoint the Publish button uses). The endpoint is picked from the
  payload shape, so one file covers both modes.

## Camp vs group: what differs on the wire

Both modes share the same question/part shape (`title`, `description`,
`instruction`, `startingPoints`, `maxScore`, `sectionOrder`, `parts`,
`questions`, `passages`). What differs is the targeting and scheduling block:

| | camp | group |
|---|---|---|
| Endpoint | `/api/tutor/camp-simulations` | `/api/tutor/group-simulations` |
| Targeting | `"targetCampGroups": [{"campGroupId": "84"}]` | `"groupAccess": [{"groupId": "34"}]` (the class id in the page URL — the site answers 422 "At least one target group is required." without it) |
| Dates | optional `releaseDate` / `dueDate` | **required** `releaseDate` / `dueDate` |
| Flags | optional `isHidden`, `showScoreToStudents` | always sent (`isHidden: true`, `showScoreToStudents: false` unless overridden) |
| Question extras | — | `hasQuestionImage`, `hasNewQuestionImage`, `hasAnswerImage`, `hasNewAnswerImage` (all `false` on a fresh upload), plus empty `deletedQuestionIds` / `deletedPassageIds` / `deletedPartIds`, `tutorAccess: []` |

The group body must use the site's own top-level key set exactly — no
`targetGroups` key. That key was tried before and the server 422s on the
unknown key with the misleading message "Release date is required.", even
when `releaseDate` is present. `test_tex2sim.py` pins the exact key set.

A group payload captured from the real editor looks like this (abridged):

```jsonc
{
  "title": "...", "description": "...", "instruction": "...",
  "startingPoints": 0, "maxScore": 10,
  "dueDate": "2026-10-01T10:30:00.000Z",
  "showScoreToStudents": false,
  "sectionOrder": ["standalone"],
  "releaseDate": "2026-09-25T06:00:00.000Z",
  "isHidden": true,
  "parts": [],
  "questions": [{
    "tempId": "z9ulomo", "tempPartId": null,
    "type": "text", "text": "tes 3", "useLatex": false, "orderIndex": 0,
    "pointsCorrect": 10, "pointsIncorrect": -10, "pointsUnanswered": 0,
    "options": [], "answerKey": [{ "answer": "w" }],
    "hasQuestionImage": false, "hasNewQuestionImage": false,
    "hasAnswerImage": false, "hasNewAnswerImage": false,
    "questionImagePath": null, "questionImageMimeType": null,
    "answerImagePath": null,   "answerImageMimeType": null
  }],
  "passages": [],
  "deletedQuestionIds": [], "deletedPassageIds": [], "deletedPartIds": [],
  "groupAccess": [], "tutorAccess": []
}
```

| UI button        | `type`            | `answerKey`                          |
| ---------------- | ----------------- | ------------------------------------ |
| Multiple Choice  | `multiple_choice` | `[{optionIndex: n}]`                 |
| Multiple Answers | `checkboxes`      | `[{optionIndex: a}, {optionIndex: b}]` |
| Short Answer     | `text`            | `[{answer: "42"}]`                   |
| Long Text        | `paragraph`       | `[{answer: "..."}]`                  |
| True / False     | `true_false`      | `[{answer: "true"}]`, options True/False |

`useLatex: true` makes the field render as LaTeX (inline `$...$`, display `$$...$$`).
Auth is `Authorization: Bearer <access_token>`, taken from the `sb-db-auth-token`
cookie — `upload.js` does that for you, so you must be logged in on that tab.

## What the .tex needs

The sample file already follows all of this:

* `\title{...}` — becomes the simulation title (override with `--title`).
* One `\section*{Section A: Multiple Choice (3 points each)}` per part. The
  `(N points each)` is what sets `pointsCorrect`; sections whose heading contains
  "Instruction" or "Answer Key" are skipped.
* One `\item` per question, inside that section's `enumerate`.
* `% Answer: C` on a comment line **directly above** the `\item`. Anything after
  the first `(` is ignored, so `% Answer: C  (the gaps are 4, 8, ...)` works.
  For open-ended, `% Answer: 3025`.
* Options as `\quad (A) 59 \quad (B) 61 ...` — they must run A, B, C in order.
  No `(A)` line ⇒ the question is treated as Short Answer.
* A `\textbf{Instructions:}` block before the first `\section` becomes the
  simulation instruction (a flat `enumerate` inside it turns into numbered
  lines; a nested `itemize` inside one rule stays with that rule as
  `a)`, `b)` lines, since the site cannot render `\begin{itemize}`).
  Without one, the payload uses the built-in default: the standard
  no-timer / no-cheating / no-calculator rules. `--instruction "..."` overrides
  both.
* A `\begin{itemize}` inside a question stem is flattened the same way
  (`\item` lines become `a)`, `b)`, …), so no `\begin{...}` ever reaches
  `payload.json`.

## Run it

Camp:

```bash
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json --mode camp --camp-group 84
```

Group (regular class) — `--group`, `--release-date` and `--due-date` are all
required. `--group` is the class id in the page URL
(`.../classes/group/34` means `--group 34`); leaving it out gets a 422
("At least one target group is required."). Write the dates as
`HH:MM-DD-MM-YYYY` (a dot works too: `19.00-25-09-2026`).
They are read as Jakarta time (UTC+7) and converted to the UTC form the site
stores; full ISO-8601 (`2026-09-25T06:00:00.000Z`) is also accepted as-is:

```bash
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json --mode group \
  --group 34 --release-date 13:00-25-09-2026 --due-date 17:30-01-10-2026
```

If you ever mean a different zone for the short form, add e.g.
`--timezone +00:00`. Anything that is neither the short form nor ISO is
rejected before anything is written.

`--mode` can be omitted when unambiguous: passing `--camp-group` implies camp,
otherwise group is assumed (and the dates become mandatory). Useful extras:

* `--starting-score N` / `--max-score N` (`--max-score` defaults to
  startingPoints + all question points, which is what the site's "Score Balance"
  check wants).
* `--points-incorrect N` — wrong-answer points on every question (default 0;
  the captured group quiz used `-10`).
* `--hidden` / `--visible`, `--show-score` / `--hide-score` — group payloads
  default to hidden with the score hidden; camp payloads only send these when
  passed explicitly.
* `--camp-group` can be repeated for several camp groups; `--release-date` /
  `--due-date` also work in camp mode as optional scheduling.

To find a camp group id: on the create page, open DevTools → Network, and look at
`/api/tutor/camp-classes/<campId>/camp-groups`. A group class id is the number
in the class URL, e.g. `.../classes/group/34?tab=simulation`.

## Updating an existing group simulation (the normal case)

Group sims already exist on the site as placeholders. Content updates do not
POST — the site PATCHes `/api/tutor/group-simulations/<groupId>/<simId>/edit`
(the URL is visible in the Network tab when saving through the web UI), with a
body shaped exactly like the editor's: empty `groupAccess`, and the old
questions' `dbId` values in `deletedQuestionIds`:

```bash
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json --mode group \
  --group 34 --sim-id 172 --delete-question-ids 8194 \
  --release-date 13:00-25-09-2026 --due-date 17:30-01-10-2026
```

Find `<simId>` in that PATCH URL and the question `dbId` in the editor payload
(the question object carries both `tempId` and `dbId`). Then in the console:

```js
await uploadSim(PAYLOAD, {simId: 172, groupId: 34})
```

`upload.js` picks PATCH and the `/edit` URL from those two options. If the
payload is still in create shape (targeting keys, dates), it reshapes the body
to the PATCH shape itself and says what it changed — no rebuild needed.

## Uploading from the browser console

Works the same for camp and group; the payload shape picks the endpoint.

1. Build `0-scripts/payload.json` with `tex2sim.py` (see the camp / group
   commands above).
2. Open the simulation page for that camp or group, logged in as tutor:
   camp: `.../tutor-dashboard/classes/camp/<id>/simulation/create`;
   group: `.../classes/group/<id>` (tab simulation).
3. Open DevTools → Console tab.
4. Open `0-scripts/upload.js` here in the repo, copy the whole file, paste it
   into the console, Enter. It prints `uploadSim() ready.`
5. Copy the payload into the console. The reliable way on a Mac: run
   `pbcopy < 0-scripts/payload.json` in a terminal, then in the console type
   `var PAYLOAD = ` , paste, Enter. (Pasting straight inside
   `await uploadSim(` … `)` also works but is harder to fix on a typo.)
6. Dry run first: `await uploadSim(PAYLOAD, {dryRun:true})` — Enter. It prints
   the endpoint, part/question counts, and any validation errors. Nothing is
   sent.
7. If the dry run is clean, send it: `await uploadSim(PAYLOAD)` — Enter.
   The mode is auto-detected (`targetCampGroups` ⇒ camp POST,
   otherwise group POST; `{simId, groupId}` ⇒ group PATCH).

### Worked examples

| # | Flow | Status |
|---|---|---|
| 1 | Camp POST (create a new sim) | scripted below — live POST not yet verified, dry-run first |
| 2 | Group PATCH (fill a placeholder sim) | verified live end to end |
| 3 | Group POST (create a new sim) | not supported — the server 422s; create the placeholder in the web UI, then use 2 |
| 4 | Camp PATCH (update an existing sim) | works like 2 — `.../camp-simulations/<campId>/<simId>/edit?campGroupId=<campGroupId>` |

#### 1. Camp POST — new simulation for camp group 32

Two different ids, do not mix them up:

- camp id: the camp itself, in the page URL
  (`.../tutor-dashboard/classes/camp/<campId>/simulation/create`) — this is
  the page you open in the browser.
- camp-group id: the group inside the camp, from
  `/api/tutor/camp-classes/<campId>/camp-groups` (DevTools → Network) — this
  is what goes to `--camp-group`. Repeat `--camp-group` for several groups.

```bash
# build (--camp-group is YOUR id from the lookup above, not 32)
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json \
  --mode camp --camp-group <campGroupId> --max-score 100 --starting-score 0
```

```js
// console on the camp's simulation/create page (upload.js pasted, PAYLOAD set)
await uploadSim(PAYLOAD, {dryRun:true})   // check first, sends nothing
await uploadSim(PAYLOAD)                  // the real POST
```

#### 2. Group PATCH — fill placeholder sim 172 in group 34

Same commands as "Updating an existing group simulation" above, with the
proven Review Quiz numbers filled in:

```bash
# build
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json --mode group \
  --group 34 --sim-id 172 --delete-question-ids 8194 \
  --release-date 13:00-25-09-2026 --due-date 17:30-01-10-2026 \
  --starting-score 12 --max-score 100
```

```js
// console on any page of group 34 (upload.js pasted, PAYLOAD set)
await uploadSim(PAYLOAD, {dryRun:true, simId:172, groupId:34})
await uploadSim(PAYLOAD, {simId:172, groupId:34})   // the real PATCH
```

For another class, swap in its group id, sim id (from the PATCH URL
`.../group-simulations/<group>/<sim>/edit`), and placeholder question `dbId`.

#### 3. Camp PATCH — replace test content of sim 174 (camp 32, group 109)

```bash
# build (--delete-part-ids drops the old part so no empty part lingers)
python3 0-scripts/tex2sim.py paper.tex -o 0-scripts/payload.json --mode camp \
  --camp-group 109 --camp-id 32 --sim-id 174 \
  --delete-question-ids 8192 --delete-part-ids 849
```

```js
// console on any page of the camp (upload.js pasted, PAYLOAD set)
await uploadSim(PAYLOAD, {dryRun:true, simId:174, campId:32, campGroupId:109})
await uploadSim(PAYLOAD, {simId:174, campId:32, campGroupId:109})   // the real PATCH
```

Find the three ids in the site's own edit URL
`.../camp-simulations/<campId>/<simId>/edit?campGroupId=<campGroupId>` and the
old `dbId`s in its editor payload. Unlike group updates, the camp PATCH body
carries no dates — scheduling stays as the sim already has it.

On success the console prints the created simulation; reload the class page to
see it. Diagram questions (flagged with `!` by `tex2sim.py`) still need their
PNGs attached by hand in the web UI afterwards.

`upload.js` validates per mode before sending: camp payloads must carry
`targetCampGroups`, group payloads must carry a non-empty `groupAccess` plus
both dates and no camp-group id — so a mode mix-up fails loudly in the console
instead of as a server 400/422. Payloads that still carry the old `targetGroups`
key are rejected by the validator with a rebuild message.

## Limits

* **Diagrams are not handled.** tikzpicture, tabular, `\fbox` card rows and
  `figure` blocks cannot be uploaded through this endpoint without first
  uploading an image. The script flags those questions; render each one to PNG
  and attach it in the web UI afterwards (the question itself is already there,
  so it is just an image drop).
* Passages (`Add Passage`) are not generated; `passages` is always `[]`.
* The group PATCH update flow is verified live end to end. The camp POST and
  camp PATCH flows are wired from a captured edit request but not yet fired
  live — do the first camp upload as a dry run, then for real on a throwaway
  title so you can see the result before using it on a live paper.
