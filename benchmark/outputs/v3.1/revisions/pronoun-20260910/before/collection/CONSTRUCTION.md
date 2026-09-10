# WorldLine Core v3.1 构造完成记录

2026-09-10 已完成全部 **112/112** 条 prompt：保留原有 16 条，本轮按项目现有 VAPI / `gemini-3.7-flash` 配置新增 96 条。构造与独立审校使用同一模型的不同请求。每条实际输入、返回模型和阶段输出保存在各自的 `run.json` 与 `attempt-*.json` 中。

## 产物

- [公开 prompt 总览](prompts.md)：112 个完整文本块，与逐例 `prompt.txt` 一致。
- [公开 JSON](public_prompts.json)：112 条结构化 prompt，不含隐藏答案。
- [完整清单](core_matrix.manifest.json)：112 complete，0 pending。
- [全量校验报告](validation.report.json)：0 errors。
- [构造记录 JSON](construction.summary.json)：模型、分布、原文件保护和导出校验值。

## 校验结果

- 112 个唯一 case signature、112 条唯一公开 prompt。
- 7 个场景各 16 条；4 种任务各 28 条。
- 三镜头、四镜头各 56 条；三人、四人各 56 条；反打、俯拍各 56 条。
- 14 段已核验素材各用于 8 条，来源记录及性别、衣服颜色均衡检查通过。
- 所有样本均保存五阶段结果，最终 LLM audit 无阻断问题；公开文本、结构化 prompt、内部状态和 annotations 一致。
- 原有 16 条样本的 100 个文件已逐一核对 SHA-256，全部未改动。
- 本轮修复对应的 24 项离线测试通过；导出 JSON 的逐镜头内容与原文件逐一比对一致。

## 接口修复与恢复

主批次遇到 7 条事件 schema 转换错误和 1 条连接中断，均保留原始失败记录。故事 schema 现按已知任务选择单一严格事件结构，避免部分 VAPI Gemini 路由不能处理的联合分支；事件含义、公开 prompt 和隐藏答案规则保持原样。读超时和断连纳入既有有限重试，单阶段最多 4 次请求，401/402/403 仍立即停止新增 case。

8 条失败样本均已成功补跑，共复用 16 个精确匹配的已成功阶段；已经通过的样本未重写。历史请求中保留真实使用的旧 schema，补跑请求记录修复后的 schema，不回写日志。

主批次日志：[construction-20260910.log](construction-20260910.log)。补跑日志：[construction-20260910-retry1.log](construction-20260910-retry1.log)。

## 当前范围

本次完成的是 prompt 构造、模型审校和离线集合验证，没有新增视频生成或视频评测。候选集仍需人工复核和既定裁判校准，未声明为正式冻结数据集；现有 16 条视频的分数仍属于原 v5 评测。
