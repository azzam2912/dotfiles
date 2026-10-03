#!/usr/bin/env bash
# Compile OSN/OSK/OSP contest .tex files to PDF and clean up build artifacts.
#
# Usage:
#   scripts/compile.sh [--here] [LEVEL] [GRADE]
#   scripts/compile.sh [--here] --dir FOLDER
#   scripts/compile.sh [--here] -d FOLDER
#
#   LEVEL: osk | osp | osn | all   (default: all)
#   GRADE: sma | smp | sd | all   (default: all)
#   FOLDER: a single folder name (searched anywhere in the repo, case-
#           insensitive) or a path relative to the repo root. Compiles only
#           that one folder, ignoring LEVEL/GRADE.
#   --here  Put each PDF directly next to its .tex file instead of in a
#           "pdf/" subfolder. Use this for folders that keep their PDFs
#           beside the sources, e.g. "SG Gathered Questions/".
#
# Examples:
#   scripts/compile.sh                  # compile everything
#   scripts/compile.sh osk              # all OSK folders (SD/SMP/SMA)
#   scripts/compile.sh osn sma          # only "OSN SMA"
#   scripts/compile.sh all smp          # every SMP folder (OSK/OSN/OSP)
#   scripts/compile.sh --dir "OSN SMA"  # only "OSN SMA", found anywhere
#   scripts/compile.sh -d "Japan MO Preliminary"
#   scripts/compile.sh --here -d "SG Gathered Questions"
#
# Runs pdflatex twice per file (so \pageref{LastPage} etc. resolve), writing
# output into a "pdf/" subfolder of each matched directory, then deletes
# .aux/.log/.out/.toc/.synctex.gz/.fls/.fdb_latexmk/.pre, leaving only the
# .pdf (and any .errlog) in that pdf/ subfolder.
#
# Errors are tolerated: pdflatex runs in nonstopmode without -halt-on-error,
# so a missing 0Figure/ image or a broken macro in one problem does not stop
# the file - the PDF is still produced with every other problem intact. Such
# a file is reported as "OK with N error(s)" and the offending log excerpts
# are kept next to the PDF as <name>.errlog. Only a file that produces no
# PDF at all counts as failed (and sets a non-zero exit status).

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_DIR="$ROOT/OSN - Olimpiade Sains Nasional"

ARTIFACT_EXTS=(aux log out toc synctex.gz fls fdb_latexmk bbl blg bcf run.xml nav snm vrb pre)

HERE=0
if [ "${1:-}" = "--here" ] || [ "${1:-}" = "--flat" ]; then
  HERE=1
  shift
fi

matched_dirs=()

if [ "${1:-}" = "--dir" ] || [ "${1:-}" = "-d" ]; then
  FOLDER="${2:-}"
  if [ -z "$FOLDER" ]; then
    echo "Usage: scripts/compile.sh --dir FOLDER"
    exit 1
  fi

  # A path (relative to repo root or cwd) is used as-is; otherwise search
  # the whole repo for a directory whose name matches (case-insensitive).
  if [ -d "$FOLDER" ]; then
    matched_dirs=("$(cd "$FOLDER" && pwd)")
  elif [ -d "$ROOT/$FOLDER" ]; then
    matched_dirs=("$ROOT/$FOLDER")
  else
    while IFS= read -r -d '' dir; do
      matched_dirs+=("$dir")
    done < <(find "$ROOT" -type d \( -name .git -o -name pdf \) -prune -o -type d -iname "$FOLDER" -print0)

    case "${#matched_dirs[@]}" in
      0)
        echo "No folder found matching '$FOLDER'"
        exit 1
        ;;
      1) ;;
      *)
        echo "Multiple folders match '$FOLDER':"
        printf '  %s\n' "${matched_dirs[@]#$ROOT/}"
        echo "Pass a full path (relative to the repo root) to disambiguate."
        exit 1
        ;;
    esac
  fi
else
  LEVEL="${1:-all}"
  GRADE="${2:-all}"
  LEVEL="$(echo "$LEVEL" | tr '[:upper:]' '[:lower:]')"
  GRADE="$(echo "$GRADE" | tr '[:upper:]' '[:lower:]')"

  case "$LEVEL" in
    osk|osp|osn|all) ;;
    *) echo "Unknown LEVEL '$LEVEL' (expected osk|osp|osn|all)"; exit 1 ;;
  esac
  case "$GRADE" in
    sma|smp|sd|all) ;;
    *) echo "Unknown GRADE '$GRADE' (expected sma|smp|sd|all)"; exit 1 ;;
  esac

  if [ ! -d "$BASE_DIR" ]; then
    echo "Cannot find '$BASE_DIR'"
    exit 1
  fi

  while IFS= read -r -d '' dir; do
    name="$(basename "$dir")"
    first_word="$(echo "$name" | awk '{print tolower($1)}')"
    last_word="$(echo "$name" | awk '{print tolower($NF)}')"

    [ "$LEVEL" != "all" ] && [ "$first_word" != "$LEVEL" ] && continue
    [ "$GRADE" != "all" ] && [ "$last_word" != "$GRADE" ] && continue

    matched_dirs+=("$dir")
  done < <(find "$BASE_DIR" -mindepth 2 -maxdepth 2 -type d -print0 | sort -z)

  if [ "${#matched_dirs[@]}" -eq 0 ]; then
    echo "No folders matched LEVEL='$LEVEL' GRADE='$GRADE' under '$BASE_DIR'"
    exit 1
  fi
fi

echo "Matched folders:"
printf '  %s\n' "${matched_dirs[@]#$ROOT/}"
echo

total=0
failed=0
warned=0

for dir in "${matched_dirs[@]}"; do
  if [ "$HERE" -eq 1 ]; then
    outdir="$dir"
  else
    outdir="$dir/pdf"
    mkdir -p "$outdir"
  fi
  while IFS= read -r -d '' texfile; do
    total=$((total + 1))
    rel="${texfile#$ROOT/}"
    base="$(basename "${texfile%.tex}")"
    reloutdir="${outdir#$ROOT/}"
    echo "==> Compiling $rel"

    # Run twice from the repo root so 0Figure/ paths resolve, sending
    # generated output into dir/pdf/ via -output-directory.
    #
    # Deliberately no -halt-on-error: nonstopmode keeps going past missing
    # figures, undefined control sequences and the like, so a file with a
    # few broken problems still yields a PDF containing all the rest. A
    # file only counts as failed when no PDF comes out at all.
    for pass in 1 2; do
      (cd "$ROOT" && pdflatex -interaction=nonstopmode \
          -output-directory="$outdir" "$texfile" >/dev/null 2>&1) || true
    done

    if [ ! -f "$outdir/$base.pdf" ]; then
      echo "    FAILED - no PDF produced, see $reloutdir/$base.errlog"
      [ -f "$outdir/$base.log" ] && cp "$outdir/$base.log" "$outdir/$base.errlog"
      failed=$((failed + 1))
      continue
    fi

    # A PDF exists; report (but tolerate) any errors TeX recovered from.
    nerr=0
    if [ -f "$outdir/$base.log" ]; then
      nerr="$(grep -c '^!' "$outdir/$base.log" || true)"
    fi
    if [ "$nerr" -gt 0 ]; then
      echo "    OK with $nerr error(s) - PDF written, details in $reloutdir/$base.errlog"
      grep -A 3 '^!' "$outdir/$base.log" > "$outdir/$base.errlog" 2>/dev/null
      warned=$((warned + 1))
    fi
  done < <(find "$dir" -maxdepth 1 -name '*.tex' -print0 | sort -z)
done

echo
echo "Cleaning up build artifacts..."
for dir in "${matched_dirs[@]}"; do
  if [ "$HERE" -eq 1 ]; then
    outdir="$dir"
  else
    outdir="$dir/pdf"
  fi
  # Only the artifacts of the .tex files in this folder, so --here never
  # deletes anything belonging to an unrelated file sitting alongside.
  while IFS= read -r -d '' texfile; do
    base="$(basename "${texfile%.tex}")"
    for ext in "${ARTIFACT_EXTS[@]}"; do
      rm -f "$outdir/$base.$ext"
    done
  done < <(find "$dir" -maxdepth 1 -name '*.tex' -print0)
done

echo
echo "Done: $total file(s) processed, $warned with recovered errors, $failed with no PDF."
[ "$failed" -eq 0 ]
