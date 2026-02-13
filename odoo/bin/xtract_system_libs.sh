#!/usr/bin/env bash
set -euo pipefail

xtract() {
  local archive="$1"
  local target_dir="$2"
  local -a tar_opts=()

  [[ -f "$archive" ]] || return 0

  case "$archive" in
    *.tar.zst) tar_opts=(-I zstd) ;;
    *.tar.gz|*.tgz) tar_opts=(-z) ;;
    *)
      echo "xtract: unsupported archive format: $archive" >&2
      return 1
      ;;
  esac

  (
    cd "$target_dir" || exit 1
    tar "${tar_opts[@]}" -xpf "$archive" \
      --same-owner \
      --xattrs --xattrs-include='*' \
      2> >(grep \
            -vF "Permission denied" \
            -vF "Cannot set POSIX ACLs" \
            >&2 || true)
  ) && rm -f "$archive"
}

# --- run in parallel ---
pids=()

xtract /opt/venv.tar.gz  /opt & pids+=("$!")
xtract /opt/venv.tar.zst /opt & pids+=("$!")
xtract /usr/share.tar.gz /usr & pids+=("$!")
xtract /usr/share.tar.zst /usr & pids+=("$!")

# --- wait and propagate failure ---
rc=0
for pid in "${pids[@]}"; do
  if ! wait "$pid"; then
    rc=1
  fi
done

exit "$rc"
