#!/usr/bin/env bash
# Live preview: recompile a .tex on every save and refresh the open PDF.
#
# Usage:
#   0-scripts/watch.sh [--here] [--no-open] NAME_OR_PATH
#
#   NAME: the .tex filename, with or without the .tex extension. The script
#         searches the whole repo for it, exactly like compile-one.sh.
#
#   --here      Keep the PDF beside the .tex instead of in a "pdf/" subfolder
#               (use for "SG Gathered Questions/").
#   --no-open   Don't open the PDF viewer; just watch and rebuild.
#
# Examples:
#   0-scripts/watch.sh 050926_Angles
#   0-scripts/watch.sh --here divisibility-g3-4
#
# Press Ctrl-C to stop. Build artifacts are cleaned up on exit, leaving the
# PDF. Polls the .tex once a second and runs pdflatex from the repo root, so
# azzam.sty and 0Figure/ resolve. (latexmk -pvc is not used: it mis-parses
# the session filenames, which contain dots, e.g. "..._14.00-15.30_...".)
# Opens the PDF in Skim when available (it reloads in place and keeps your
# scroll position); falls back to the system default viewer.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ARTIFACT_EXTS=(aux log out toc synctex.gz fls fdb_latexmk bbl blg bcf run.xml
               nav snm vrb pre lof lot idx ind ilg auxlock xdv)

HERE=0
OPEN=1
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --here|--flat) HERE=1; shift ;;
    --no-open)     OPEN=0; shift ;;
    -h|--help)     sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             args+=("$1"); shift ;;
  esac
done

if [ "${#args[@]}" -ne 1 ]; then
  echo "Usage: 0-scripts/watch.sh [--here] [--no-open] NAME_OR_PATH"
  exit 1
fi

# Same resolution rules as compile-one.sh: a path, or a bare filename found
# anywhere in the repo.
resolve_tex() {
  local arg="$1" name="${1%.tex}" base matches=()

  if [ -f "$arg" ]; then
    echo "$(cd "$(dirname "$arg")" && pwd)/$(basename "$arg")"; return 0
  elif [ -f "$name.tex" ]; then
    echo "$(cd "$(dirname "$name.tex")" && pwd)/$(basename "$name.tex")"; return 0
  elif [ -f "$ROOT/$arg" ]; then
    echo "$ROOT/$arg"; return 0
  elif [ -f "$ROOT/$name.tex" ]; then
    echo "$ROOT/$name.tex"; return 0
  fi

  base="$(basename "$name").tex"
  while IFS= read -r -d '' f; do
    matches+=("$f")
  done < <(find "$ROOT" -type d \( -name .git -o -name pdf \) -prune -o -type f -iname "*$(basename "$name")*.tex" -print0)

  case "${#matches[@]}" in
    0) echo "No .tex file found matching '$arg'" >&2; return 1 ;;
    1) echo "${matches[0]}"; return 0 ;;
    *)
      {
        echo "Multiple .tex files match '$arg':"
        printf '  %s\n' "${matches[@]#$ROOT/}"
        echo "Pass more of the name, or a full path, to disambiguate."
      } >&2
      return 1
      ;;
  esac
}

texfile="$(resolve_tex "${args[0]}")" || exit 1

dir="$(dirname "$texfile")"
base="$(basename "${texfile%.tex}")"

if [ "$HERE" -eq 1 ]; then
  outdir="$dir"
else
  outdir="$dir/pdf"
  mkdir -p "$outdir"
fi

pdf="$outdir/$base.pdf"

cleanup() {
  trap - EXIT INT TERM   # so an INT/TERM does not also fire the EXIT trap
  echo
  echo "Stopping watch; cleaning build artifacts..."
  for ext in "${ARTIFACT_EXTS[@]}"; do
    rm -f "$outdir/$base.$ext"
  done
  echo "PDF kept: ${pdf#$ROOT/}"
  exit 0
}
trap cleanup EXIT INT TERM

# One build: twice through pdflatex so \tableofcontents and friends settle,
# reporting any errors TeX recovered from. Never -halt-on-error, so a missing
# 0Figure/ image still yields a PDF with everything else intact.
build() {
  local pass nerr
  for pass in 1 2; do
    (cd "$ROOT" && pdflatex -interaction=nonstopmode \
        -output-directory="$outdir" "$texfile" >/dev/null 2>&1) || true
  done

  if [ ! -f "$outdir/$base.pdf" ]; then
    echo "    FAILED - no PDF produced"
    return
  fi

  nerr=0
  [ -f "$outdir/$base.log" ] && nerr="$(grep -c '^!' "$outdir/$base.log" || true)"
  if [ "$nerr" -gt 0 ]; then
    echo "    $nerr error(s) recovered:"
    grep -A 3 '^!' "$outdir/$base.log" 2>/dev/null | head -20 | sed 's/^/      /'
  else
    echo "    ok"
  fi
}

echo "Watching: ${texfile#$ROOT/}"
echo "PDF:      ${pdf#$ROOT/}"
echo "Save the .tex to rebuild. Ctrl-C to stop."
echo

echo "==> Building $(date +%H:%M:%S)"
build

if [ "$OPEN" -eq 1 ] && [ -f "$pdf" ]; then
  if [ -d /Applications/Skim.app ]; then
    open -a Skim "$pdf"
  else
    open "$pdf"
  fi
fi

# Poll the source's modification time once a second and rebuild on change.
last="$(stat -f %m "$texfile" 2>/dev/null || echo 0)"
while true; do
  sleep 1
  [ -f "$texfile" ] || continue
  now="$(stat -f %m "$texfile" 2>/dev/null || echo 0)"
  if [ "$now" != "$last" ]; then
    last="$now"
    echo "==> Rebuilding $(date +%H:%M:%S)"
    build
  fi
done
