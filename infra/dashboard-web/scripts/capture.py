#!/usr/bin/env python3
"""截图脚本 - 使用系统 Playwright 浏览器"""

import http.client
import time
import sys
from pathlib import Path

# 使用已缓存的 Playwright 浏览器
PLAYWRIGHT_CHROMIUM = Path.home() / "Library/Caches/ms-playwright/chromium-1200/chrome-mac/Chromium.app/Contents/MacOS/Chromium"

def wait_for_server(url="localhost", port=19400, max_wait=30):
    """等待服务器启动"""
    print(f"等待服务器 {url}:{port}...")
    for i in range(max_wait):
        try:
            conn = http.client.HTTPConnection(url, port, timeout=1)
            conn.request("GET", "/api/status")
            response = conn.getresponse()
            if response.status == 200:
                print("✓ 服务器已就绪")
                return True
        except:
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    return False

def capture_screenshots():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("错误：未找到 playwright Python 模块")
        print("请运行: pip3 install playwright --break-system-packages")
        sys.exit(1)
    
    if not wait_for_server():
        print("\n服务器启动超时")
        sys.exit(1)
    
    screenshots_dir = Path(__file__).parent.parent / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    
    with sync_playwright() as p:
        # 使用系统 Chromium
        browser = p.chromium.launch(
            executable_path=str(PLAYWRIGHT_CHROMIUM) if PLAYWRIGHT_CHROMIUM.exists() else None,
            headless=True
        )
        
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        
        routes = [
            ("/", "home"),
            ("/calendar", "calendar"),
            ("/news", "news"),
            ("/sanity", "sanity"),
        ]
        
        for path, name in routes:
            url = f"http://localhost:19400{path}"
            print(f"\n截图: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)  # 等待数据加载
            
            screenshot_path = screenshots_dir / f"{name}.png"
            page.screenshot(path=str(screenshot_path), full_page=True)
            print(f"✓ 已保存 {screenshot_path}")
        
        browser.close()
    
    print("\n✅ 所有截图完成！")

if __name__ == "__main__":
    capture_screenshots()
