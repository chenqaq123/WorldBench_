# 指代消歧修订完成记录

2026-09-10：已修复 **9 条新 prompt、9 个镜头**中的明确对话指代歧义。每处发言者均按原有故事规划确认，原始人物、动作、座位、镜头、来源和隐藏答案保持不变。

本次为 assistant 对已生成 Content 的最小文字修改，随后通过当前 VAPI / `gemini-3.7-flash` 发起 **9 次真实审校，9/9 通过**。原始 LLM 输出、请求日志和审校结果未被回写；当前 `run.json` 的 `editorial_revisions` 记录修改来源，新审校请求明确包含修改后的完整 prompt。

## 核验结果

- 112/112 条完成，全量结构与一致性验证 0 错误。
- 新增消歧检查准确命中修订前的 9 处问题，修订后均不再命中。
- 28 项相关离线测试通过；单一明确前文的 he/she、离场句的 his/her seat、明确的前者/后者引用仍允许。
- 原有 16 条及其他 87 条样本共 103 条保持逐文件字节一致。
- 全部 112 条隐藏注释与故事规划均未改变。
- Markdown 总览和公开 JSON 已更新，并逐条与逐例文件核对一致。

## 修改明细

### WL-CORE-GAME-ENTRY-3P-REV-4S · Shot 2

[当前 prompt](../../WL-CORE-GAME-ENTRY-3P-REV-4S/prompt.txt) · [修订前快照](before/cases/WL-CORE-GAME-ENTRY-3P-REV-4S/prompt.txt) · [新审校结果](audits/WL-CORE-GAME-ENTRY-3P-REV-4S/response.json)

**原文：** A woman in a blue shirt enters and sits in the empty place. A woman in a white shirt asks about the article submissions, and she replies with the suggested edits.

**修订：** A woman in a blue shirt enters and sits in the empty place. A woman in a white shirt asks about the article submissions, and the newcomer replies with the suggested edits.

**原故事规划：** Subject B enters and takes the empty place. Subject A asks about the article submissions, and Subject B replies with the suggested edits.

### WL-CORE-GAME-ENTRY-4P-REV-3S · Shot 2

[当前 prompt](../../WL-CORE-GAME-ENTRY-4P-REV-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-GAME-ENTRY-4P-REV-3S/prompt.txt) · [新审校结果](audits/WL-CORE-GAME-ENTRY-4P-REV-3S/response.json)

**原文：** A man in a green shirt enters and sits in the empty place. A man in a red shirt asks whether reversing words alters the meaning, and he answers that the meaning changes.

**修订：** A man in a green shirt enters and sits in the empty place. A man in a red shirt asks whether reversing words alters the meaning, and the newcomer answers that the meaning changes.

**原故事规划：** Subject B enters and takes the empty place. Subject A asks whether reversing words alters the meaning, and Subject B answers that the meaning changes.

### WL-CORE-GAME-SWAP-3P-TOP-4S · Shot 2

[当前 prompt](../../WL-CORE-GAME-SWAP-3P-TOP-4S/prompt.txt) · [修订前快照](before/cases/WL-CORE-GAME-SWAP-3P-TOP-4S/prompt.txt) · [新审校结果](audits/WL-CORE-GAME-SWAP-3P-TOP-4S/response.json)

**原文：** A woman in a purple shirt and a woman in a red shirt exchange seats, and she asks about the presentation of the creative contributions.

**修订：** A woman in a purple shirt and a woman in a red shirt exchange seats, and the former asks about the presentation of the creative contributions.

**原故事规划：** Subject A and Subject B exchange their established seats. Subject A asks about the presentation of the creative contributions.

### WL-CORE-LIVING-ENTRY-3P-REV-3S · Shot 2

[当前 prompt](../../WL-CORE-LIVING-ENTRY-3P-REV-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-LIVING-ENTRY-3P-REV-3S/prompt.txt) · [新审校结果](audits/WL-CORE-LIVING-ENTRY-3P-REV-3S/response.json)

**原文：** A woman in a green shirt enters and sits in the empty place. A woman in a red shirt asks whether the refreshments for the visit are ready, and she replies that they are unavailable.

**修订：** A woman in a green shirt enters and sits in the empty place. A woman in a red shirt asks whether the refreshments for the visit are ready, and the newcomer replies that they are unavailable.

**原故事规划：** Subject B enters and takes the empty place. Subject A asks whether the refreshments for the visit are ready, and Subject B replies that they are unavailable.

### WL-CORE-LIVING-ENTRY-3P-TOP-3S · Shot 2

[当前 prompt](../../WL-CORE-LIVING-ENTRY-3P-TOP-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-LIVING-ENTRY-3P-TOP-3S/prompt.txt) · [新审校结果](audits/WL-CORE-LIVING-ENTRY-3P-TOP-3S/response.json)

**原文：** A woman in a green shirt enters and sits in the empty place. A woman in a red shirt asks about the refreshments, and she replies that the market lacked the ingredients.

**修订：** A woman in a green shirt enters and sits in the empty place. A woman in a red shirt asks about the refreshments, and the newcomer replies that the market lacked the ingredients.

**原故事规划：** Subject B enters and takes the empty place. Subject A asks about the refreshments, and Subject B replies that the market lacked the ingredients.

### WL-CORE-MEETING-ENTRY-4P-REV-3S · Shot 3

[当前 prompt](../../WL-CORE-MEETING-ENTRY-4P-REV-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-MEETING-ENTRY-4P-REV-3S/prompt.txt) · [新审校结果](audits/WL-CORE-MEETING-ENTRY-4P-REV-3S/response.json)

**原文：** A man in a white shirt asks a man in a purple shirt to explain the account, and he answers with the details.

**修订：** A man in a white shirt asks for an explanation of the account, and a man in a purple shirt answers with the details.

**原故事规划：** Subject A asks Subject D to explain the account, and Subject D answers with the details.

### WL-CORE-MEETING-ENTRY-4P-TOP-3S · Shot 3

[当前 prompt](../../WL-CORE-MEETING-ENTRY-4P-TOP-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-MEETING-ENTRY-4P-TOP-3S/prompt.txt) · [新审校结果](audits/WL-CORE-MEETING-ENTRY-4P-TOP-3S/response.json)

**原文：** A man in a white shirt asks a man in a purple shirt to proceed with the account, and he answers with the details of the case.

**修订：** A man in a white shirt asks to hear the account, and a man in a purple shirt answers with the details of the case.

**原故事规划：** Subject A asks Subject D to proceed with the account, and Subject D answers with the details of the case.

### WL-CORE-MEETING-SWAP-4P-REV-3S · Shot 2

[当前 prompt](../../WL-CORE-MEETING-SWAP-4P-REV-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-MEETING-SWAP-4P-REV-3S/prompt.txt) · [新审校结果](audits/WL-CORE-MEETING-SWAP-4P-REV-3S/response.json)

**原文：** A man in a purple shirt and a man in a red shirt exchange seats, and he asks him to help review the account.

**修订：** A man in a purple shirt and a man in a red shirt exchange seats, and the former asks the latter to help review the account.

**原故事规划：** Subject A and Subject B exchange their established seats. Subject A asks Subject B to help review the account.

### WL-CORE-MEETING-SWAP-4P-TOP-3S · Shot 2

[当前 prompt](../../WL-CORE-MEETING-SWAP-4P-TOP-3S/prompt.txt) · [修订前快照](before/cases/WL-CORE-MEETING-SWAP-4P-TOP-3S/prompt.txt) · [新审校结果](audits/WL-CORE-MEETING-SWAP-4P-TOP-3S/response.json)

**原文：** A man in a purple shirt and a man in a red shirt exchange seats, and he asks him to assist with the case.

**修订：** A man in a purple shirt and a man in a red shirt exchange seats, and the latter asks the former to assist with the case.

**原故事规划：** Subject A and Subject B exchange their established seats. Subject B asks Subject A to assist with the case.

## 防止同类问题再次出现

构造器和审校器增加一致的指代规则：同一镜头已引入两名同性人物后，新发言分句不能仅靠未限定的 he/she 指派说话人。可将动作直接接到身份上，或在只列出两人的上下文中使用明确的前者/后者；入场镜头可用 the newcomer 指向刚入场的唯一人物。每人每镜头仅一次身份锚点的原规则仍保留。

本地检查只拦截这一明确模式，不冒充通用自然语言指代解析器。当前复核仍是 assistant 文本检查与模型审校，未新增视频实验或真人标签。

[机器可读修订记录](summary.json) · [修改列表](changes.json) · [审校汇总](audit-results.json)
