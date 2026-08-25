#!/usr/bin/env bash
# 用 Apple Developer ID 签名 + 公证(发布给同事用需要)
#
# 前置条件:
#   1. Apple Developer 账号(年费 $99)
#   2. 在 Xcode 登录后,从 https://developer.apple.com/account/resources/certificates/list
#      下载 "Developer ID Application" 证书,装到 Keychain
#   3. 在 https://developer.apple.com/account/resources/authkeys/list
#      创建 App-specific password,保存到 Keychain:
#        xcrun notarytool store-credentials "notary-credentials" \
#          --apple-id "your@email.com" \
#          --team-id "ABCDE12345" \
#          --password "xxxx-xxxx-xxxx-xxxx"
#
# 用法:
#   ./sign-and-notarize.sh <Developer ID 名称>
#
# 例如:
#   ./sign-and-notarize.sh "Developer ID Application: Your Name (ABCDE12345)"
#
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "用法: $0 <Developer ID 名称>"
    echo "例如: $0 \"Developer ID Application: 你的名字 (TEAMID)\""
    exit 1
fi

DEVELOPER_ID="$1"
APP_NAME="林卡电表"
ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$ROOT/.build/$APP_NAME.app"

if [[ ! -d "$APP_PATH" ]]; then
    echo "❌ 找不到 $APP_PATH,先跑 ./build-app.sh release"
    exit 1
fi

echo "==> 1. 重新 build(release)..."
cd "$ROOT"
swift build -c release

# 重新组装 .app bundle
echo "==> 2. 组装 .app bundle..."
bash ./build-app.sh release > /dev/null

echo "==> 3. 用 Developer ID 替换 ad-hoc 签名..."
codesign --force --deep --options runtime \
    --sign "$DEVELOPER_ID" \
    "$APP_PATH"

echo "==> 4. 验证签名..."
codesign --verify --deep --strict --verbose=2 "$APP_PATH"
echo "    ✓ 签名验证通过"

# 检查 entitlements 是否正确嵌入
echo ""
echo "==> 5. 当前 entitlements:"
codesign -d --entitlements - "$APP_PATH" 2>&1 | grep -A 20 "<plist" || true

echo ""
echo "==> 6. 上传到 Apple Notary Service 做公证..."
ZIP_PATH="$ROOT/.build/$APP_NAME-notarize.zip"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

xcrun notarytool submit "$ZIP_PATH" \
    --keychain-profile "notary-credentials" \
    --wait

echo ""
echo "==> 7. Staple 票据(把公证结果嵌回 .app,离线也能用)..."
xcrun stapler staple "$APP_PATH"

echo ""
echo "==> 8. 验证公证..."
xcrun stapler validate "$APP_PATH"

echo ""
echo "✅ 完成!现在可以分发 $APP_PATH:"
echo "   open \"$APP_PATH\""
echo "   或者 zip 后给同事"