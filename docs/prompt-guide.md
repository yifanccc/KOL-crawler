# Prompt Guide

每个 KOL 可覆盖 system prompt、user prompt 与 JSON schema；未覆盖时使用服务端默认值。user prompt 使用原帖内容作为输入，不应要求模型改写或丢弃原文。

所有展示字段必须为中文。`stance` 只能是 `bullish`、`bearish`、`neutral`、`unclear`，对应 `stance_cn` 为 `多`、`空`、`中性`、`不明确`；没有标的时 `symbols=[]`。Dashboard 核心字段为 `summary_cn`、`stance`、`stance_cn`、`symbols`、`market`、`key_points`、`confidence`、`importance`、`tags`、`action_hint`、`source_language`、`translated_text_cn`、`risk_warning`。

自定义 schema 必须以 object 为根、设置 `additionalProperties=false` 并包含全部核心字段。管理员保存时由服务端做权威校验；不兼容 schema 会返回 422。模型响应按“直接 JSON、代码围栏、首个平衡对象、一次规范化修复、启发式 fallback”有界处理，畸形响应不会阻断原帖入库或覆盖 `raw_posts.raw_text`。
