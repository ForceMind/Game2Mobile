# Game2Mobile visual identity / 视觉标识

The icon is an original illustration combining a mobile-device frame and a game controller. It is independent of artwork, logos and trademarks belonging to any commercial game.

图标采用手机轮廓与游戏手柄的组合，独立于任何商业游戏的 Logo、商标和美术资源。它是 Game2Mobile 当前的初版视觉标识，不代表已有正式商标注册。

- **Design source / 设计源文件:** [`game2mobile-icon.svg`](game2mobile-icon.svg)
- **iOS asset / iOS 产物:** [`AppIcon1024.png`](../../dm/ios/Assets.xcassets/AppIcon.appiconset/AppIcon1024.png)
- **macOS packaging / macOS 图标:** `dm/tools/mac_app.sh` builds `Game2Mobile.icns` from the same tracked PNG at package time.
- **Colors / 颜色:** background `#0C1822`, bright lime `#B6FF69`, green `#8BFAB4`, teal `#43DDC1`.

To regenerate the deterministic RGB icon / 重新生成不透明 RGB 图标：

```bash
python3 -m pip install cairosvg pillow
python3 scripts/render_app_icon.py
python3 scripts/render_app_icon.py --check
```

The source SVG has no third-party font or downloaded image dependencies. Do **not** replace the old game's branding by tracing or recoloring its registered logos.

设计源文件不含第三方字体或网络图片。不要通过描摹、换色商业游戏 Logo 的方式生成品牌图标。
