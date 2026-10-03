#!/usr/bin/env bash
# Compile one or more .tex files to PDF and clean up build artifacts.
#
# Usage:
#   scripts/compile-one.sh [--here] NAME_OR_PATH [NAME_OR_PATH ...]
#
#   NAME: the .tex filename, with or without the .tex extension
#         (e.g. "osn-sma-2002" or "osn-sma-2002.tex"). The script searches
#         the whole repo for a matching file. You can also pass a relative
#         or absolute path directly.
#
#   --here  Put the PDF directly next to the .tex file instead of in a
#           "pdf/" subfolder. Use this for folders that keep their PDFs
#           beside the sources, e.g. "SG Gathered Questions/".
#
# Examples:
#   scripts/compile-one.sh osn-sma-2002
#   scripts/compile-one.sh --here simulasi-mini-osn-sd-2026
#   scripts/compile-one.sh --here "SG Gathered Questions/"*.tex
#
# Runs pdflatex twice (so \pageref{LastPage}, \tableofcontents etc. resolve),
# then deletes .aux/.log/.out/.toc/.synctex.gz/... , leaving only the .pdf
# (and an .errlog when TeX recovered from errors).
#
# Errors are tolerated: nonstopmode without -halt-on-error, so a missing
# 0Figure/ image or a broken macro in one problem still yields a PDF with
# every other problem intact.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ARTIFACT_EXTS=(aux log out toc synctex.gz fls fdb_latexmk bbl blg bcf run.xml
               nav snm vrb pre lof lot idx ind ilg auxlock xdv)

HERE=0
args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --here|--flat) HERE=1; shift ;;
    -h|--help)     sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             args+=("$1"); shift ;;
  esac
done

if [ "${#args[@]}" -eq 0 ]; then
  echo "Usage: scripts/compile-one.sh [--here] NAME_OR_PATH [NAME_OR_PATH ...]"
  exit 1
fi

# Resolve one argument to an absolute path of an existing .tex file.
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
  done < <(find "$ROOT" -type d \( -name .git -o -name pdf \) -prune -o -type f -iname "$base" -print0)

  case "${#matches[@]}" in
    0) echo "No .tex file found matching '$arg'" >&2; return 1 ;;
    1) echo "${matches[0]}"; return 0 ;;
    *)
      {
        echo "Multiple .tex files match '$arg':"
        printf '  %s\n' "${matches[@]#$ROOT/}"
        echo "Pass a full path to disambiguate."
      } >&2
      return 1
      ;;
  esac
}

total=0
failed=0
warned=0

for arg in "${args[@]}"; do
  texfile="$(resolve_tex "$arg")" || { failed=$((failed + 1)); continue; }

  total=$((total + 1))
  dir="$(dirname "$texfile")"
  base="$(basename "${texfile%.tex}")"

  if [ "$HERE" -eq 1 ]; then
    outdir="$dir"
  else
    outdir="$dir/pdf"
    mkdir -p "$outdir"
  fi
  reloutdir="${outdir#$ROOT/}"

  echo "==> Compiling ${texfile#$ROOT/}"

  # Run twice from the repo root so 0Figure/ paths and azzam.sty resolve,
  # sending generated output into $outdir via -output-directory.
  for pass in 1 2; do
    (cd "$ROOT" && pdflatex -interaction=nonstopmode \
        -output-directory="$outdir" "$texfile" >/dev/null 2>&1) || true
  done

  if [ ! -f "$outdir/$base.pdf" ]; then
    echo "    FAILED - no PDF produced, see $reloutdir/$base.errlog"
    [ -f "$outdir/$base.log" ] && cp "$outdir/$base.log" "$outdir/$base.errlog"
    failed=$((failed + 1))
  else
    nerr=0
    [ -f "$outdir/$base.log" ] && nerr="$(grep -c '^!' "$outdir/$base.log" || true)"
    if [ "$nerr" -gt 0 ]; then
      echo "    OK with $nerr error(s) - details in $reloutdir/$base.errlog"
      grep -A 3 '^!' "$outdir/$base.log" > "$outdir/$base.errlog" 2>/dev/null
      warned=$((warned + 1))
    fi
    echo "    PDF: $reloutdir/$base.pdf"
  fi

  # Clean up only the artifacts belonging to this file, so --here never
  # touches unrelated files sitting in the same folder.
  for ext in "${ARTIFACT_EXTS[@]}"; do
    rm -f "$outdir/$base.$ext"
  done
done

echo
echo "Done: $total file(s) processed, $warned with recovered errors, $failed failed."
[ "$failed" -eq 0 ]
