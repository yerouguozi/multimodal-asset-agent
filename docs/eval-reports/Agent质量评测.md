# Agent 回答质量评测

- 生成时间：2026-09-10
- 规划模型：deepseek-chat（LLM 规划）
- 用例：9 条（检索 4 / 画像 1 / 时间戳定位 1 / 片段定位 1 / 库外反例 1 / 详情 1）

## 逐用例结果

| 查询 | 预期工具 | 实际工具 | 工具命中 | 引用 | 忠实度 | 延迟 |
|---|---|---|---|---|---|---|
| 找一些城市夜景的图片 | search_assets | search_assets | ✓ | ✓ | ✓ | 14908ms |
| 有没有适合助眠的音频 | search_assets | search_assets | ✓ | ✓ | ✓ | 4199ms |
| 深度学习相关的资料有哪些 | search_assets | search_assets | ✓ | ✓ | ✓ | 3030ms |
| white noise for sleep | search_assets | search_assets | ✓ | 合法 | ✓ | 13199ms |
| 库里都有些什么素材 | domain_profile | domain_profile | ✓ | 合法 | ✓ | 3823ms |
| 会议录音里提到了什么 | find_moment | find_moment | ✓ | 合法 | ✓ | 2045ms |
| 从招聘简章里找一下岗位要求那段 | find_passage | find_passage | ✓ | ✓ | ✓ | 3389ms |
| 量子物理相关的素材 | search_assets | search_assets | ✓ | 合法 | ✓ | 2570ms |
| #1 这个素材的详情 | get_asset_detail | get_asset_detail | ✓ | ✓ | ✓ | 1336ms |

## 汇总

- 工具规划命中：9/9
- 引用合法率：4/5（期望引用的用例中，引用存在且全部通过硬校验）
- 库外反例如实说空：1/1
- 忠实度通过（LLM 裁判）：9/9
- 延迟：平均 5388ms / P95 14908ms

## 结论

- 防幻觉第二道防线（引用硬校验）可用数字说话：引用合法率即上方指标；
- 忠实度裁判衡量「答案是否被工具结果支撑」，是 Prompt 约束之外的可量化补充；
- 库外反例验证「工具结果为空时如实说明」，防编造话术落地。