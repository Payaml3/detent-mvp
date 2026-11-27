#!/usr/bin/env bash
# Verify a DekernAI webhook delivery with openssl. Run: bash verify_webhook.sh ../webhook-vectors.txt
set -uo pipefail

# docs:start
# verify_webhook SECRET HEADER BODY_FILE [NOW] [TOLERANCE]: exit 0 if the DekernAI-Signature header
# matches the raw body (read from a file, byte for byte) and is within the time window.
verify_webhook() {
  local secret=$1 header=$2 body_file=$3 now=${4:-$(date +%s)} tolerance=${5:-300}
  local timestamp="" part key value expected
  local -a signatures=()
  IFS=',' read -r -a parts <<< "$header"
  [[ $header == *, ]] && parts+=("")
  for part in "${parts[@]}"; do
    [[ $part == *=* ]] || return 1
    key=${part%%=*} value=${part#*=}
    key=${key//[[:space:]]/} value=${value//[[:space:]]/}
    if [[ $key == t ]]; then
      [[ -z $timestamp && $value =~ ^[0-9]+$ ]] || return 1
      timestamp=$value
    elif [[ $key == v1 ]]; then
      signatures+=("$value")
    fi
  done
  [[ -n $timestamp && ${#signatures[@]} -gt 0 ]] || return 1
  local age=$(( now - timestamp ))
  (( ${age#-} <= tolerance )) || return 1
  expected=$( { printf '%s.' "$timestamp"; cat "$body_file"; } \
    | openssl dgst -sha256 -hmac "$secret" -r | cut -d' ' -f1)
  for s in "${signatures[@]}"; do
    [[ $s == "$expected" ]] && return 0
  done
  return 1
}
# docs:end

failures=0
body_file=$(mktemp)
trap 'rm -f "$body_file"' EXIT
while IFS='|' read -r name expect secret now header body; do
  [[ -z $name || $name == \#* ]] && continue
  printf '%s' "$body" > "$body_file"
  if verify_webhook "$secret" "$header" "$body_file" "$now"; then got=ok; else got=fail; fi
  if [[ $got != "$expect" ]]; then
    echo "FAIL $name: expected $expect"
    failures=$((failures + 1))
  fi
done < "$1"
if (( failures )); then echo "curl: $failures vector(s) failed"; exit 1; fi
echo "curl: all vectors pass"
