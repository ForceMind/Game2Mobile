#!/bin/bash
# 当前改写产物的代号只写在一处：dm/PRODUCT（一行，如 3.3.94012-r28）。换代只改那一行。
# 用法：product.sh name <种类>  → 3.3.94012-r28-<种类>（种类：touch / rules / keypage）
#       product.sh path <种类>  → 本机缺省产物目录 $DM_ROOT/build/cache/dm/out/<name>
#       product.sh rev           → r28
#       product.sh check         → 核对三种缓存的源码指纹、模块文件和未完成标记
#       product.sh build         → 重出三种产物（keypage / rules / touch）到本机缺省目录
# The codename of the current rewrite build output is written in exactly one place: dm/PRODUCT (one line, e.g. 3.3.94012-r28). A revision bump changes only that line.
# Usage: product.sh name <kind>  → 3.3.94012-r28-<kind> (kind: touch / rules / keypage)
#       product.sh path <kind>  → local default build output directory $DM_ROOT/build/cache/dm/out/<name>
#       product.sh rev           → r28
#       product.sh build         → rebuild the three kinds of build output (keypage / rules / touch) into the local default directory
set -u
P=$(head -1 "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/PRODUCT") || exit 2
[ -n "$P" ] || { echo "dm/PRODUCT 为空" >&2; exit 2; }
case "${1:-}" in
  name) echo "$P-${2:?种类}";;
  path) echo "${DM_ROOT:-$HOME/dm-work}/build/cache/dm/out/$P-${2:?种类}";;
  rev)  echo "${P##*-}";;
  check)  # Reuse the existing rewriter source receipt; no game contents are printed.
    HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
    WANT=$(shasum -a 256 "$HERE/patch_nso.py" | awk '{print $1}') || exit 1
    [ -n "$WANT" ] || exit 1
    for k in keypage rules touch; do
      O=${DM_ROOT:-$HOME/dm-work}/build/cache/dm/out/$P-$k
      [ -d "$O" ] && [ ! -e "$O/.product-building" ] || exit 1
      HAVE=$(awk 'NR == 1 {print $1}' "$O/build_src.sha256" 2>/dev/null)
      COMPLETE=$(awk 'NR == 1 {print $1}' "$O/product.complete.sha256" 2>/dev/null)
      [ "$HAVE" = "$WANT" ] && [ "$COMPLETE" = "$WANT" ] || exit 1
      for m in main sdk subsdk0; do
        [ -s "$O/$m.patched.bin" ] && [ -s "$O/$m.fixups.tsv" ] &&
          [ -f "$O/$m.gates.tsv" ] || exit 1
      done
    done;;
  build)   # 用本工作树的改写器重出三种产物到本机缺省目录（换代 / 改了 patch_nso.py 之后跑）。种类 → 规则集：keypage = 原生；rules = 触屏规则、不带宿主私有门；touch = 触屏规则 + 私有门 | Rebuild the three kinds of build output with this worktree's rewriter into the local default directory (run after a revision bump / after changing patch_nso.py). Kind → rule set: keypage = native; rules = touchscreen rules, without host-private gates; touch = touchscreen rules + private gates
    HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); PY=${DM_PY:-${DM_ROOT:-$HOME/dm-work}/build/cache/dm/venv/bin/python3}; NSO=${DM_NSO_DIR:-${DM_ROOT:-$HOME/dm-work}/data/switch/3.3.94012/Update/ExeFS}
    for k in keypage rules touch; do O=${DM_ROOT:-$HOME/dm-work}/build/cache/dm/out/$P-$k
      mkdir -p "$O" || exit 1
      # Keep this sentinel on interruption or failure. patch_nso.py writes its
      # source receipt per module, so that receipt alone is not a completion flag.
      touch "$O/.product-building" || exit 1
      case $k in keypage) E=(DM_RULESET=native);; rules) E=(DM_RULESET=touch-run-v4 DM_PRIVATE_GATES=0);; touch) E=(DM_RULESET=touch-run-v4);; esac
      for m in main sdk subsdk0; do env "${E[@]}" "$PY" "$HERE/patch_nso.py" "$NSO/$m" "$O" "$m" > "$O/$m.patch.log" 2>&1 || { echo "🔴 $k $m 改写失败：$(tail -2 "$O/$m.patch.log")" >&2; exit 1; }; done
      # Copy the existing receipt only after every module completed. Older
      # caches without this completion record are rebuilt once by setup.sh.
      cp "$O/build_src.sha256" "$O/product.complete.sha256" || exit 1
      rm -f "$O/.product-building" || exit 1
      echo "$P-$k 已出：$(ls "$O" | wc -l | tr -d ' ') 个文件"; done;;
  *) echo "用法：product.sh name|path <种类> | rev | check | build" >&2; exit 2;;
esac
