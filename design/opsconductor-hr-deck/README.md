# 运筹 OpsConductor · HR 展示 Deck

14 页、约 9 分钟的横向翻页 HTML PPT，面向 HR / 非技术面试官展示跨境电商场景、多 Agent 编排、产品完成度与工程可信度。

## 打开

推荐用本地 HTTP 打开，确保本地动效模块和图片正常加载：

```bash
# 仓库根目录
python -m http.server 8090 --directory design/opsconductor-hr-deck
# http://127.0.0.1:8090/
```

也可以直接双击 `index.html`；`file://` 下浏览器会阻止本地 ES module，动效会自动回退到 CDN，断网时内容仍可读。

演示快捷键：`← / →` 翻页，`ESC` 总览，`P` 演讲者模式；演讲者备注已按 14 页写好，计划讲述 9 分钟。

## 页面结构

| 页 | 主题 | 内容 |
|---|---|---|
| 01 | hero dark | 封面：把十段运营，收进案桌 |
| 02 | light | 复杂度：一个人盯不住十段链路 |
| 03 | hero light | 主张：不是全能 Agent，而是 Agent 团队 |
| 04 | dark | 产品：统一台前调度首页 |
| 05 | light | 场景：十段跨境运营链路 |
| 06 | dark | 产品：阶段工作台与 Agent 产出 |
| 07 | light | 架构：目标 → 计划 → 8 个 Agent → 验证 |
| 08 | dark | 治理：L0–L3 审批与写操作边界 |
| 09 | light | 治理：异常 0–72 小时 Playbook |
| 10 | light | 数据：销售额 / Agent 使用量 / 结果交付 |
| 11 | dark | 架构：canonical model + Adapter Registry |
| 12 | light | 工程：90 后端测试 / 15 前端单测 / 10 E2E |
| 13 | dark | 匹配：岗位关注与项目证据 |
| 14 | hero light | 收束：分工给 Agent，判断留给人 |

## 素材与维护

- 截图来自真实 Vue 调度台，位于 `images/`，不是手绘概念图。
- 重新生成截图（先启动 Demo）：

```bash
PORT=8010 bash scripts/demo_dispatch.sh
cd frontend
node scripts/capture-hr-screenshots.mjs
```

- 主题为 `brand`，由项目朱砂色 `#A8342A` 经 PPT skill 的受约束主题脚本生成；正文颜色全部走语义变量，没有散落 hex。
- 修改文案后运行演讲者模式校验：

```bash
node "C:/Users/DELL/.agents/skills/guizang-ppt-skill/scripts/validate-presenter-mode.mjs" \
  index.html --target-minutes 10
```
