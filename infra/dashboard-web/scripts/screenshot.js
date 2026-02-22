const { chromium } = require('playwright');
const http = require('http');

async function waitForServer(url, maxAttempts = 30) {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      await new Promise((resolve, reject) => {
        const req = http.get(url, (res) => {
          if (res.statusCode === 200) resolve();
          else reject();
        });
        req.on('error', reject);
        req.setTimeout(1000, () => reject());
      });
      console.log('服务器已就绪');
      return;
    } catch {
      process.stdout.write('.');
      await new Promise(r => setTimeout(r, 1000));
    }
  }
  throw new Error('服务器启动超时');
}

async function captureScreenshots() {
  console.log('等待服务器启动...');
  await waitForServer('http://localhost:19400');
  
  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 }
  });
  
  const routes = [
    { path: '/', name: 'home' },
    { path: '/calendar', name: 'calendar' },
    { path: '/news', name: 'news' },
    { path: '/sanity', name: 'sanity' },
  ];
  
  for (const route of routes) {
    console.log(`\n截图: ${route.path}`);
    await page.goto(`http://localhost:19400${route.path}`, { 
      waitUntil: 'networkidle',
      timeout: 30000 
    });
    await page.waitForTimeout(2000); // 等待数据加载
    await page.screenshot({ 
      path: `screenshots/${route.name}.png`,
      fullPage: true 
    });
    console.log(`✓ 已保存 screenshots/${route.name}.png`);
  }
  
  await browser.close();
  console.log('\n所有截图完成！');
}

captureScreenshots().catch(console.error);
