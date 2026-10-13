#!/usr/bin/env bash
# 把 court-shooting-checklist.md 生成为 PDF。
#
# 为什么要这个脚本：markdown 的 `- [ ]` 会被渲染成 HTML 复选框控件，
# 打印时完全不可见（38 个勾选框会全部消失）。所以先替换成字符 ☐ 再渲染。
# 源文件保持 task list 语义不变，只有生成 PDF 时才做替换。
set -euo pipefail
cd "$(dirname "$0")"

PDF_BIN="${MAKE_PDF_BIN:-$HOME/.claude/skills/gstack/make-pdf/dist/pdf}"
if [ ! -x "$PDF_BIN" ]; then
  echo "找不到 make-pdf 二进制：$PDF_BIN" >&2
  echo "设置 MAKE_PDF_BIN 环境变量指向它，或参考 make-pdf skill 的 ./setup" >&2
  exit 1
fi

sed 's/^- \[ \]/- ☐/' court-shooting-checklist.md > .pdf-build.md
trap 'rm -f .pdf-build.md' EXIT

"$PDF_BIN" generate --page-size a4 --no-confidential \
  --title "到球场的拍摄清单" \
  .pdf-build.md court-shooting-checklist.pdf
