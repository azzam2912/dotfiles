/* upload.js — paste this whole file into the Chrome DevTools console while you
 * are on the simulation-create page (you must be logged in as the tutor):
 *
 *   camp:  https://www.stargeneration.id/tutor-dashboard/classes/camp/<id>/simulation/create
 *   group: https://www.stargeneration.id/tutor-dashboard/classes/group/<id>  (tab simulation)
 *
 * Then run:
 *     await uploadSim(PAYLOAD)                // PAYLOAD = contents of payload.json
 *     await uploadSim(PAYLOAD, {dryRun:true}) // validate + print, send nothing
 *     await uploadSim(PAYLOAD, {mode:"group"}) // override the auto-detected mode
 *     await uploadSim(PAYLOAD, {endpoint:"/api/tutor/groups/34/simulations?x=y"})
 *       // post to an exact URL (with query string) captured from the site's
 *       // own Network tab, instead of the default endpoint for the mode
 *
 * Updating an existing group simulation (the normal case: the placeholder sim
 * already exists on the site) goes to a different URL with PATCH, not POST:
 *     await uploadSim(PAYLOAD, {simId:172, groupId:34})
 * Build PAYLOAD with: tex2sim.py ... --group 34 --sim-id 172
 *   --delete-question-ids 8194   (dbId of the placeholder question to drop).
 * The group and sim ids are in the site's own edit URL:
 * /api/tutor/group-simulations/<groupId>/<simId>/edit (see Network tab).
 *
 * Same for camp updates:
 *     await uploadSim(PAYLOAD, {simId:174, campId:32, campGroupId:109})
 * Build PAYLOAD with: tex2sim.py ... --camp-group 109 --camp-id 32
 *   --sim-id 174 --delete-question-ids 8192 [--delete-part-ids 849].
 * The ids are in the site's own edit URL:
 * /api/tutor/camp-simulations/<campId>/<simId>/edit?campGroupId=<campGroupId>.
 *
 * The mode is auto-detected from the payload: a payload with
 * targetCampGroups posts to /api/tutor/camp-simulations, anything else
 * posts to /api/tutor/group-simulations.
 *
 * Group bodies must use the site's own key set exactly: group targeting goes
 * in groupAccess, and there must be no targetGroups key. An unknown top-level
 * key makes the server 422 with a misleading message such as
 * "Release date is required." even when releaseDate is present.
 */

( function () {

  const ENDPOINTS = {
    camp: "/api/tutor/camp-simulations",
    group: "/api/tutor/group-simulations",
  };

  function detectMode(p) {
    if (p.targetCampGroups && p.targetCampGroups.length) return "camp";
    return "group";
  }

  function getToken() {
    const raw = document.cookie
      .split(";")
      .map((c) => c.trim())
      .filter((c) => /^sb-[^=]*-auth-token(\.\d+)?=/.test(c))
      .sort()
      .map((c) => c.slice(c.indexOf("=") + 1))
      .join("");
    if (!raw) throw new Error("auth cookie not found — are you logged in on this tab?");
    let v = decodeURIComponent(raw);
    if (v.startsWith("base64-")) v = atob(v.slice(7));
    const session = JSON.parse(v);
    const token = session.access_token || (session.currentSession && session.currentSession.access_token);
    if (!token) throw new Error("no access_token inside the auth cookie");
    return token;
  }

  // Reshape a create-shaped body into the site's PATCH shape in place.
  // Returns what changed, for the console log. Update bodies carry no
  // targeting keys or dates — the URL says where they go.
  function sanitizeForUpdate(p, mode) {
    const fixed = [];
    if (mode === "camp") {
      for (const k of ["targetCampGroups", "releaseDate", "dueDate",
                       "isHidden", "showScoreToStudents"]) {
        if (k in p) { delete p[k]; fixed.push("dropped " + k); }
      }
      if (!("additionalCampGroups" in p)) {
        p.additionalCampGroups = []; fixed.push("added additionalCampGroups: []");
      }
    } else {
      for (const k of ["targetCampGroups", "targetGroups"]) {
        if (k in p) { delete p[k]; fixed.push("dropped " + k); }
      }
      if (p.groupAccess && p.groupAccess.length) {
        p.groupAccess = []; fixed.push("emptied groupAccess");
      }
    }
    return fixed;
  }

  function validate(p, mode, isUpdate) {
    const errs = [];
    if (!p.title) errs.push("title is empty");
    if (!p.instruction) errs.push("instruction is empty");
    if (mode === "camp") {
      if (!isUpdate && (!p.targetCampGroups || !p.targetCampGroups.length)) {
        errs.push("camp mode needs targetCampGroups (rebuild the payload with --mode camp --camp-group <id>)");
      }
    } else if (isUpdate) {
      // targeting keys are stripped by sanitizeForUpdate above; nothing to check
    } else {
      if (p.targetCampGroups && p.targetCampGroups.length)
        errs.push("group mode must not have targetCampGroups (rebuild the payload with --mode group)");
      if (p.targetGroups && p.targetGroups.length)
        errs.push("payload still carries targetGroups — rebuild with the current tex2sim.py " +
                  "(group targeting now goes in groupAccess); the site 422s on the unknown key");
      if (!p.groupAccess || !p.groupAccess.length)
        errs.push('group mode needs groupAccess (rebuild with --group <id>) — ' +
                  'the site answers 422 "At least one target group is required." without it');
      if (!p.releaseDate) errs.push("group mode needs releaseDate");
      if (!p.dueDate) errs.push("group mode needs dueDate");
    }
    const total = (p.questions || []).reduce((s, q) => s + (q.pointsCorrect || 0), 0);
    if (p.startingPoints + total !== p.maxScore)
      errs.push(`score balance: startingPoints(${p.startingPoints}) + question points(${total}) = ` +
                `${p.startingPoints + total}, but maxScore is ${p.maxScore}`);
    (p.questions || []).forEach((q, i) => {
      const n = i + 1;
      if (!q.text) errs.push(`Q${n}: empty text`);
      if (q.type === "multiple_choice" || q.type === "checkboxes") {
        if (!q.options || q.options.length < 2) errs.push(`Q${n}: needs at least 2 options`);
        if (!q.answerKey || !q.answerKey.length) errs.push(`Q${n}: no correct option marked`);
        (q.answerKey || []).forEach((k) => {
          if (typeof k.optionIndex !== "number" || k.optionIndex >= (q.options || []).length)
            errs.push(`Q${n}: answer key points at option ${k.optionIndex}, which does not exist`);
        });
      } else if (!q.answerKey || !q.answerKey.length || !String(q.answerKey[0].answer || "").length) {
        errs.push(`Q${n}: no expected answer`);
      }
      const ids = (p.parts || []).map((x) => x.tempId);
      if (q.tempPartId && !ids.includes(q.tempPartId)) errs.push(`Q${n}: tempPartId not in parts`);
    });
    return errs;
  }

  window.uploadSim = async function (payload, opts) {
    opts = opts || {};
    if (typeof payload === "string") payload = JSON.parse(payload);
    let mode = opts.mode || detectMode(payload);
    if (!ENDPOINTS[mode]) throw new Error(`unknown mode "${mode}" — want "camp" or "group"`);
    const isUpdate = opts.simId != null;
    let method = "POST", url = opts.endpoint;
    if (url) {
      if (isUpdate) method = "PATCH";
    } else if (!isUpdate) {
      url = ENDPOINTS[mode];
    } else if (opts.groupId != null) {
      method = "PATCH";
      url = `/api/tutor/group-simulations/${opts.groupId}/${opts.simId}/edit`;
    } else if (opts.campId != null && opts.campGroupId != null) {
      method = "PATCH";
      mode = "camp";
      url = `/api/tutor/camp-simulations/${opts.campId}/${opts.simId}/edit?campGroupId=${opts.campGroupId}`;
    } else {
      throw new Error('update needs ids: group → {simId, groupId}; ' +
        'camp → {simId, campId, campGroupId}');
    }
    payload = JSON.parse(JSON.stringify(payload));  // sanitize below must not mutate the caller's object
    if (isUpdate) {
      const fixed = sanitizeForUpdate(payload, mode);
      if (fixed.length)
        console.warn("update: reshaped body to the PATCH shape (" + fixed.join(", ") + ")");
    }
    const errs = validate(payload, mode, isUpdate);
    console.log(
      `%c${payload.title} [${mode}]`, "font-weight:bold",
      `\n  endpoint:  ${url}`,
      `\n  method:    ${method}`,
      `\n  parts:     ${(payload.parts || []).length}`,
      `\n  questions: ${(payload.questions || []).length}`,
      `\n  maxScore:  ${payload.maxScore}` +
      (mode === "group" ? `\n  release:   ${payload.releaseDate}\n  due:       ${payload.dueDate}` : "") +
      (mode === "camp"
        ? `\n  groups:    ${(payload.targetCampGroups || []).map((g) => g.campGroupId).join(", ")}`
        : `\n  groups:    ${(payload.groupAccess || []).map((g) => g.groupId).join(", ")}`));
    if (errs.length) {
      console.error("validation failed:\n  - " + errs.join("\n  - "));
      return { ok: false, errors: errs };
    }
    if (opts.dryRun) {
      console.log("%cdry run — nothing sent", "color:#888");
      return { ok: true, dryRun: true, payload };
    }
    const res = await fetch(url, {
      method: method,
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + getToken(),
      },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    let body;
    try { body = JSON.parse(text); } catch (e) { body = text; }
    if (!res.ok) {
      console.error("HTTP " + res.status, body);
      console.error("sent top-level keys: " + Object.keys(payload).join(", "));
      return { ok: false, status: res.status, body };
    }
    console.log("%ccreated", "color:green;font-weight:bold", body);
    return { ok: true, body };
  };

  console.log("uploadSim() ready. Run: await uploadSim(<payload.json contents>)");
})();
