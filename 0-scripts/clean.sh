#!/usr/bin/env bash
# Delete LaTeX build artifacts (.aux/.log/.out/... ) left behind by pdflatex.
#
# Usage:
#   scripts/clean.sh [--dir FOLDER] [--pdf] [--empty-dirs] [-n|--dry-run]
#
#   --dir FOLDER   Clean only this folder (recursively). Accepts a path
#                  relative to the repo root or cwd, or a bare folder name
#                  searched for anywhere in the repo (case-insensitive).
#                  Default: the whole repository.
#   --pdf          Also delete .pdf files. Off by default, since the PDFs in
#                  each pdf/ subfolder are the point of compiling.
#   --empty-dirs   Also remove pdf/ subfolders left empty afterwards.
#   -n, --dry-run  List what would be deleted without deleting anything.
#                  (With --empty-dirs, folders are not reported in a dry run,
#                  since nothing was actually removed from them yet.)
#
# Examples:
#   scripts/clean.sh                       # clean artifacts repo-wide
#   scripts/clean.sh -n                    # preview only
#   scripts/clean.sh --dir "OSN SMP"       # just that folder
#   scripts/clean.sh --pdf --empty-dirs    # wipe compile output entirely
#
# .git/ is never touched. Extensions match the ones the compile scripts
# generate, plus the .errlog files they write for recovered errors.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

ARTIFACT_EXTS=(aux log out toc synctex.gz fls fdb_latexmk bbl blg bcf run.xml
               nav snm vrb pre errlog lof lot idx ind ilg glo gls acn acr alg
               figlist makefile auxlock upa upb xdv)

TARGET="$ROOT"
DRY_RUN=0
WITH_PDF=0
EMPTY_DIRS=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dir|-d)
      FOLDER="${2:-}"
      if [ -z "$FOLDER" ]; then
        echo "Usage: scripts/clean.sh --dir FOLDER"
        exit 1
      fi
      if [ -d "$FOLDER" ]; then
        TARGET="$(cd "$FOLDER" && pwd)"
      elif [ -d "$ROOT/$FOLDER" ]; then
        TARGET="$ROOT/$FOLDER"
      else
        matched=()
        while IFS= read -r -d '' dir; do
          matched+=("$dir")
        done < <(find "$ROOT" -type d -name .git -prune -o -type d -iname "$FOLDER" -print0)
        case "${#matched[@]}" in
          0) echo "No folder found matching '$FOLDER'"; exit 1 ;;
          1) TARGET="${matched[0]}" ;;
          *)
            echo "Multiple folders match '$FOLDER':"
            printf '  %s\n' "${matched[@]#$ROOT/}"
            echo "Pass a full path (relative to the repo root) to disambiguate."
            exit 1
            ;;
        esac
      fi
      shift 2
      ;;
    --pdf)        WITH_PDF=1; shift ;;
    --empty-dirs) EMPTY_DIRS=1; shift ;;
    -n|--dry-run) DRY_RUN=1; shift ;;
    -h|--help)    sed -n '2,26p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            echo "Unknown option '$1' (see scripts/clean.sh --help)"; exit 1 ;;
  esac
done

[ "$WITH_PDF" -eq 1 ] && ARTIFACT_EXTS+=(pdf)

# Build the find expression: -name '*.aux' -o -name '*.log' -o ...
find_args=()
for ext in "${ARTIFACT_EXTS[@]}"; do
  [ "${#find_args[@]}" -gt 0 ] && find_args+=(-o)
  find_args+=(-name "*.$ext")
done

if [ "$TARGET" = "$ROOT" ]; then
  echo "Cleaning: whole repository"
else
  echo "Cleaning: ${TARGET#$ROOT/}"
fi
[ "$WITH_PDF" -eq 1 ] && echo "Including .pdf files"
[ "$DRY_RUN" -eq 1 ] && echo "(dry run - nothing will be deleted)"
echo

count=0
while IFS= read -r -d '' f; do
  echo "  ${f#$ROOT/}"
  [ "$DRY_RUN" -eq 0 ] && rm -f "$f"
  count=$((count + 1))
done < <(find "$TARGET" -type d -name .git -prune -o -type f \( "${find_args[@]}" \) -print0 | sort -z)

removed_dirs=0
if [ "$EMPTY_DIRS" -eq 1 ]; then
  while IFS= read -r -d '' d; do
    if [ -z "$(ls -A "$d")" ]; then
      echo "  ${d#$ROOT/}/"
      [ "$DRY_RUN" -eq 0 ] && rmdir "$d"
      removed_dirs=$((removed_dirs + 1))
    fi
  done < <(find "$TARGET" -type d -name pdf -print0 | sort -z)
fi

echo
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Would delete $count file(s)$([ "$removed_dirs" -gt 0 ] && echo " and $removed_dirs empty pdf/ folder(s)")."
else
  echo "Deleted $count file(s)$([ "$removed_dirs" -gt 0 ] && echo " and $removed_dirs empty pdf/ folder(s)")."
fi
