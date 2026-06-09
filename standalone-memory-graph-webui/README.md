# Memory Graph WebUI

**神经网络记忆审核工作台** — 让 AI 的外部记忆可检查、可回滚、可信任。

---

## 🧠 什么是 Memory Graph？

Memory Graph WebUI 是一个 AI 记忆审核工作台，专为需要长期记忆的 AI Agent 设计。它将“影子写入”（shadow writes）转变为“冷静的审核室”（calm review room）：

- ✅ **审核后采纳** - 只批准真正属于记忆图谱的内容
- ✅ **用户隔离** - 用户作用域的审核队列和命名空间检查
- ✅ **可验证记忆** - 通过读回验证（readback verification）确保重要记忆成为可信召回

### 核心理念

传统 AI 记忆系统的问题：
- ❌ 静默写入，无法审核
- ❌ 错误记忆难以回滚
- ❌ 跨用户污染
- ❌ 无法追溯变更历史

Memory Graph 的解决方案：
- ✅ 所有变更进入待审队列
- ✅ 人工审核 + 自动读回验证
- ✅ 完整的变更历史和回滚能力
- ✅ 命名空间隔离保护隐私

---

## 🎨 WebUI 设计

### 设计哲学：太空中的神经网络

登录页背景采用**神经网络星空**设计，象征：
- **繁星点点** - 每个记忆节点都是宇宙中的一颗星
- **神经元连接** - 节点之间的连线代表记忆的关联
- **脉冲能量** - 节点呼吸般的脉动，模拟神经元的激活
- **飞向繁星** - 预示人类在 AI 协助下走向星辰大海

**技术实现**：
- Canvas 实时绘制 35 个神经元节点
- 200 颗闪烁的星星作为背景
- 节点间距 < 180px 自动建立连接
- 能量脉冲沿连线传递（渐变动画）
- 60fps 流畅动画，GPU 加速

### 响应式设计

- **桌面端（1280px+）**：双栏布局，完整功能展示
- **平板（768-1024px）**：自适应间距，触摸友好
- **手机（375-428px）**：单列布局，表单优先

### 配色系统

| 用途 | 颜色 | Hex/RGB |
|-----|------|---------|
| 主背景 | 深空蓝 | #070b18 |
| 神经元核心 | 靛蓝 | #6366f1 |
| 连接线 | 紫色渐变 | #8b5cf6 |
| 强调色 | 青色 | #06b6d4 |
| 成功状态 | 翠绿 | #10b981 |
| 警告状态 | 琥珀 | #f59e0b |

---

## 📦 核心功能

### 1. 审核与追溯（Review & Audit）

**Graph Changes 队列**：
- 查看所有待审核的记忆变更
- 支持创建、修改、删除三种操作
- Diff 对比查看变更前后内容
- 一键批准或回滚

**Candidates 队列**：
- 独立 Memory OS 候选队列
- 仅 `target_store=memory_graph` 可直接批准
- 读回验证（Readback Verification）
- 自动记录可回滚的变更集

**特色**：
- 中英文国际化覆盖主要导航、登录、审核、记忆浏览和设置页面
- 交错动画，列表加载如波浪展开
- 响应式移动端布局；真实设备体验仍需按部署环境验证

### 2. 记忆浏览器（Memory Explorer）

**功能**：
- 树形浏览记忆图谱结构
- 搜索记忆内容
- 编辑优先级、披露条件
- 跨域（Cross-domain）标记
- Boot URI 管理

**设计**：
- 卡片 Grid 布局（响应式列数）
- 3D 悬停效果（轻微）
- 域名标签、命名空间徽章
- 内容预览 + 截断

### 3. 记忆清理（Brain Cleanup）

**功能**：
- 扫描孤立记忆（Orphaned）
- 扫描弃用版本（Deprecated）
- 批量删除确认
- 访问日志清理

**特色**：
- 可展开查看完整内容
- Diff 对比旧版本
- 批量选择操作

### 4. 设置（Settings）

**配置项**：
- 数据库连接
- Boot URIs
- Memory Domains
- 开发者模式

---

## 🚀 技术栈

### 前端

| 技术 | 版本 | 用途 |
|-----|------|------|
| **React** | 18.x | UI 框架 |
| **Vite** | 5.x | 构建工具 |
| **Tailwind CSS** | 3.x | 样式系统 |
| **Framer Motion** | 11.x | 动画库 |
| **Lucide React** | - | 图标库 |
| **Axios** | 1.x | HTTP 客户端 |

### 后端接口

- **RESTful API**（基于 hermes-gateway）
- **认证**：Basic Auth / Session
- **端口**：8900（默认）

### 性能说明

- 当前本地构建产物约为：CSS 57.65KB，JS 510.45KB（gzip 约 160KB）
- Vite build 会提示主 JS chunk >500KB；后续可通过 code-splitting 优化
- 首屏速度、移动端耗电和 CDN 表现需要按实际部署环境验证

---

## 📱 移动端体验

### iPhone（375px - 428px）
- ✅ 登录表单大小适中
- ✅ 按钮触摸目标 ≥ 44px
- ✅ 字体清晰可读
- ✅ 单手操作友好

### iPad（768px - 1024px）
- ✅ 双栏布局正常
- ✅ 侧边栏显示
- ✅ 卡片 Grid 自适应
- ✅ 触摸响应灵敏

### 桌面（1280px+）
- ✅ 完整功能显示
- ✅ 多列 Grid 布局
- ✅ Hover 状态流畅

---

## 🌍 国际化（i18n）

### 支持语言
- 🇨🇳 简体中文（zh）
- 🇺🇸 English（en）

### 当前覆盖范围
- 导航菜单、登录页面、审核页面、记忆浏览器、设置页面已有中英文文案
- 新增页面或错误分支可能仍需要逐项补齐
- 浏览器语言自动检测：
```javascript
// 浏览器语言自动检测
const browserLang = navigator.language || 'en';
return browserLang.startsWith('zh') ? 'zh' : 'en';
```

### 手动切换
右上角语言切换按钮：`中` ↔ `EN`

---

## 🎯 使用场景

### 1. AI Agent 记忆管理
**场景**：Claude、GPT 等 AI Agent 需要长期记忆  
**痛点**：记忆错乱、跨用户污染、无法审核  
**方案**：所有记忆变更进入 Memory Graph 审核队列，人工批准后写入

### 2. 多用户 AI 服务
**场景**：团队共享一个 AI 实例  
**痛点**：A 用户的记忆被 B 用户看到  
**方案**：命名空间隔离 + 用户作用域审核队列

### 3. 企业 AI 知识库
**场景**：企业内部 AI 知识库需要质量控制  
**痛点**：错误知识难以回滚，无审计日志  
**方案**：完整的变更历史 + 一键回滚 + 读回验证

### 4. AI 研究实验
**场景**：研究者需要观察 AI 记忆演化  
**痛点**：黑盒记忆系统无法观察  
**方案**：可视化记忆图谱 + Diff 对比 + 时间线回溯

---

## 🏗️ 架构设计

### 三层架构

```
┌─────────────────────────────────────┐
│      Memory Graph WebUI             │  ← 本项目
│  (React + Tailwind + Framer Motion) │
└──────────────┬──────────────────────┘
               │ HTTP/REST
┌──────────────▼──────────────────────┐
│      hermes-gateway (Python)        │  ← 后端网关
│    - 认证                            │
│    - API 路由                        │
│    - 读回验证                        │
└──────────────┬──────────────────────┘
               │ SQL
┌──────────────▼──────────────────────┐
│     SQLite / PostgreSQL             │  ← 记忆存储
│    - memories 表                    │
│    - paths 表                        │
│    - review_snapshots 表            │
└─────────────────────────────────────┘
```

### 数据流

**记忆写入流程**：
1. AI Agent 尝试写入记忆
2. hermes-gateway 拦截写入 → 创建 snapshot
3. WebUI 展示在待审队列
4. 管理员审核 → 批准/拒绝
5. 批准：执行读回验证 → 写入图谱 → 记录变更集
6. 拒绝：丢弃变更

**记忆回滚流程**：
1. WebUI 展示 Graph Changes
2. 管理员选择变更集 → 点击"回滚"
3. hermes-gateway 执行反向操作
4. 记忆图谱恢复到变更前状态

---

## 🔒 安全特性

### 认证
- Basic Auth（默认）
- Session Cookie
- 密码存储：bcrypt 哈希

### 授权
- 命名空间隔离
- 用户作用域审核队列
- 私有记忆保护

### 审计
- 完整的操作日志
- 变更历史可追溯
- Diff 对比可查看

---

## 🛠️ 部署指南

### 前提条件
- Node.js 18+
- hermes-gateway 后端已启动（端口 8900）

### 构建

```bash
cd standalone-memory-graph-webui/frontend
npm install
npm run build
```

构建产物在 `dist/` 目录：
- `index.html` - 入口文件
- `assets/index-*.css` - 样式（~57KB）
- `assets/index-*.js` - 脚本（~502KB，gzip: 157KB）

### 部署到静态服务器

```bash
# Nginx
cp -r dist/* /var/www/html/

# Caddy
cp -r dist/* /srv/www/

# Apache
cp -r dist/* /var/www/html/
```

### 环境变量

创建 `.env.production`：
```env
VITE_API_BASE_URL=https://api.yourdomain.com
```

### CDN 加速

**Cloudflare**：
1. 添加域名到 Cloudflare
2. DNS 解析到源站
3. 开启 Auto Minify（JS, CSS）
4. 开启 Brotli 压缩
5. 缓存规则：`/assets/*` 缓存 1 年

---

## 📊 已验证指标

### 本轮本地验证
- `PYTHONPATH=backend pytest -q tests/test_namespace_isolation.py tests/test_proposal_review_action_hints.py` → 21 passed
- `npm run build` → built successfully；Vite 提示主 JS chunk >500KB

### 包大小（本地 Vite build）
```
dist/assets/index-*.css   57.65KB  (gzip: 9.56KB)
dist/assets/index-*.js   510.45KB  (gzip: 160.07KB)
```

未在本 README 中声称 Lighthouse/真机移动端分数；这些需要按实际部署域名单独测量。

---

## 🐛 已知问题与限制

### 浏览器兼容性
- ✅ Chrome 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Edge 90+
- ❌ IE 11（不支持）

### Canvas 动画
- 在低端设备上可能 < 60fps
- 可通过关闭神经网络背景优化

### 移动端
- 神经网络动画在手机上可能耗电
- 建议在设置中添加"省电模式"开关

---

## 🔮 未来规划

### v1.1（短期）
- [ ] 省电模式（关闭背景动画）
- [ ] 数字滚动动画（统计数字）
- [ ] 批量操作进度条
- [ ] 快捷键支持（Cmd+K 搜索）

### v1.2（中期）
- [ ] 记忆图谱可视化（力导向图）
- [ ] 时间线回溯（Git-like）
- [ ] WebSocket 实时更新
- [ ] 黑暗模式切换

### v2.0（长期）
- [ ] AI 辅助审核（自动分类、打分）
- [ ] 协作审核（多人同时审核）
- [ ] 插件系统（自定义审核规则）
- [ ] 记忆压缩与归档

---

## 📄 许可证

本项目是 hermes-agent-setup 补丁项目的一部分。

---

## 🙏 致谢

- **设计灵感**：Linear, Vercel, Stripe
- **动画参考**：Three.js, D3.js
- **配色系统**：Tailwind CSS Palette
- **图标库**：Lucide Icons

---

## 📞 Deployment Notes

- **Project URL**: configure your own reverse proxy/domain if exposing the WebUI.
- **Patch overlay**: `standalone-memory-graph-webui/` inside the Hermes patch project.
- **Backend service**: `memory-graph-webui.service` running the standalone FastAPI app.

---

**Memory Graph WebUI** - 让 AI 的记忆可检查、可信任、可演化。

*Built with ❤️ for the future of AI memory.*
