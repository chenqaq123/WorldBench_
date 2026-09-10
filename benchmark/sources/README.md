# WorldLine 真实素材库

十四段摘录来自六部已出版作品的 Project Gutenberg 原文。完整出处、段落定位、摘录和 SHA-256 位于 [catalog.json](catalog.json)。`collect_sources.py` 从对应 URL 下载原文、规范化空白并使用 `start_text` 精确定位；抽取三百词的连续片段，可能在句子中途截断，不改变原文词序。

|用于场景|来源片段|保留的互动依据|
|---|---|---|
|Café|`alice_riddle` / `alice_seats`|围绕谜语的争论；换座后被打断的讲述|
|Meeting room|`boat_holiday` / `holmes_arrival`|共同讨论休假方案；来访者加入咨询|
|Living room|`pride_evening` / `earnest_visit`|复述舞会经历；拜访中的招待问答|
|Dining room|`women_breakfast` / `earnest_tea`|讨论分享早餐；茶点偏好产生分歧|
|Seminar room|`pride_skills` / `holmes_account`|讨论能力标准；要求完整讲述细节|
|Game room|`women_club` / `alice_rules`|俱乐部会议；对谜语措辞的质疑|
|Kitchen|`boat_stew` / `women_housekeeping`|讨论食材准备方法；分担早餐家务|

原文入口：[Alice's Adventures in Wonderland](https://www.gutenberg.org/files/11/11-h/11-h.htm)、[Three Men in a Boat](https://www.gutenberg.org/files/308/308-h/308-h.htm)、[The Importance of Being Earnest](https://www.gutenberg.org/files/844/844-h/844-h.htm)、[Pride and Prejudice](https://www.gutenberg.org/files/1342/1342-h/1342-h.htm)、[The Adventures of Sherlock Holmes](https://www.gutenberg.org/files/1661/1661-h/1661-h.htm)、[Little Women](https://www.gutenberg.org/files/514/514-h/514-h.htm)。

生成时，第一阶段直接读取摘录，输出带 `source_id` 的故事骨架。后续将真实互动改编到固定的场所、人数与事件；演员性别、服装、场景布局和实验要求的进入/离开/换位不应被当成原作事实。公开 prompt 仅使用简短话题和必要动作，源故事中的具体台词、人物名字、服饰和道具动作不照搬。

当前 Core 每段对应八条 case。真实素材提供的是创作依据，不意味着有十四种独立空间结构，也不意味着这批数据覆盖了全部多人叙事类型。

当前 v3.1 将每个场景的两段素材分配到四种任务中，每个“场景 × 任务”内各 2 条，每段总计 8 条。完整数据见[样本清单](../outputs/v3.1/core_matrix.manifest.json)。
