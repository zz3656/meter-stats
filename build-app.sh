#!/usr/bin/env bash
# 把 SwiftPM 项目打包成 macOS .app
# 用法: ./build-app.sh [debug|release] [--install]
set -euo pipefail

CONFIG="${1:-release}"
INSTALL_FLAG="${2:-}"
APP_NAME="工程部管理系统"
ROOT="$(cd "$(dirname "$0")" && pwd)"
BUILD_DIR="$ROOT/.build"
APP_DIR="$BUILD_DIR/$APP_NAME.app"

echo "==> Building ($CONFIG)..."
cd "$ROOT"
swift build -c "$CONFIG"

BIN_PATH="$(swift build -c "$CONFIG" --show-bin-path)/Linca"
if [[ ! -x "$BIN_PATH" ]]; then
    echo "❌ 找不到 $BIN_PATH"
    exit 1
fi

echo "==> Assembling .app bundle..."
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 拷贝可执行
cp "$BIN_PATH" "$APP_DIR/Contents/MacOS/Linca"

# 拷贝 Info.plist
cp "$ROOT/Info.plist" "$APP_DIR/Contents/Info.plist"

# 拷贝资源文件:直接从源码目录拷贝(ServerManager 只读 Bundle.main.resourceURL)
# 不用 SwiftPM bundle — handlers/ 与 utils/ 各有 __init__.py,.process 会冲突
RES_SRC="$ROOT/Sources/Linca/Resources"
if [ -d "$RES_SRC" ]; then
    cp -R "$RES_SRC"/. "$APP_DIR/Contents/Resources/"
    echo "    + Resources/ (from source: server.py, index.html, handlers/, utils/, ...)"
fi

# 拷贝图标(如果存在)
if [[ -f "$ROOT/Assets/AppIcon.icns" ]]; then
    cp "$ROOT/Assets/AppIcon.icns" "$APP_DIR/Contents/Resources/AppIcon.icns"
    echo "    + AppIcon.icns"
fi

# 写 PkgInfo(没有它 macOS 会以为是旧格式)
printf "APPL????" > "$APP_DIR/Contents/PkgInfo"

echo "==> Codesigning (ad-hoc)..."
codesign --force --deep --sign - "$APP_DIR"

# 移除 macOS quarantine 属性(避免首次启动弹"无法验证开发者")
# Apple 官方推荐:用户级自装应用应该清除隔离属性
xattr -dr com.apple.quarantine "$APP_DIR" 2>/dev/null || true

echo "==> Done: $APP_DIR"

# 可选: 安装到 Applications(macOS 用户级标准位置)
# macOS 有两个 Applications 目录:
#   /Applications          系统级(需要 sudo,所有用户可见)
#   ~/Applications         用户级(无需 sudo,仅当前用户可见 — Apple 官方推荐给用户自装应用)
# 这里默认装到 ~/Applications — 跟你已有的「冰汽时代.app」位置一致
if [[ "$INSTALL_FLAG" == "--install" ]]; then
    INSTALL_PARENT="$HOME/Applications"
    mkdir -p "$INSTALL_PARENT"
    rm -rf "$INSTALL_PARENT/$APP_NAME.app"
    cp -R "$APP_DIR" "$INSTALL_PARENT/$APP_NAME.app"
    echo "==> Installed to $INSTALL_PARENT/$APP_NAME.app"
    echo "    双击运行: open \"$INSTALL_PARENT/$APP_NAME.app\""
    echo ""
    echo "    如要装到系统位置 /Applications(所有用户可见):"
    echo "      sudo cp -R \"$APP_DIR\" /Applications/"
else
    echo "    双击运行: open \"$APP_DIR\""
    echo "    安装到 Applications: ./build-app.sh release --install"
fi