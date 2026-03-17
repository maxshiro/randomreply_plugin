# 简介

Random Reply Plugin 是一个面向 AstrBot 的随机回复插件。

插件会在群聊或私聊（可配置）中记录文本与图片，并在命中概率时执行多种回复动作：
- 主随机回复（文本/图片）
- 复读
- API 图片发送
- @ 处理
- 时间戳触发回复

## 文档入口
- 架构说明：`ARCHITECTURE.md`
- 版本日志：`CHANGELOG.md`

# 功能介绍

1. 数据入库
- 文本入库：过滤链接、过滤带图消息、过滤超长文本。
- 图片入库：保存原图并记录到图片库。
- 原始消息归档：按平台/日期/群组写入 JSON。

2. 随机回复
- 主随机回复采用 1/N 触发模式。
- 文本支持加权随机和均匀随机。
- 图片采用本地优先、远端兜底。

3. 复读与 API 图片
- 复读功能独立开关与独立概率。
- API 图片功能独立开关与独立概率，支持图片流/JSON/文本 URL 解析。

4. @ 处理
- 被 @ 时可在多个动作之间按权重选择：
- 主随机回复
- 复读
- API 图片
- 固定消息

5. 时间戳随机回复
- 每分钟秒数为 0 时判定是否触发。
- 支持生效时间段。
- 支持在主随机回复与 API 图片间随机执行。

6. 定时维护
- 每日 01:00：低权重文本清理 + 远端备份/本地保留。
- 每日 01:30：缓存目录过期文件清理。

7. 会话与存储范围控制
- 私聊处理开关。
- 群组白名单/黑名单。
- 群独立文本库（可迁移旧全局库）。

# 程序逻辑

1. 消息事件主流程
- 接收消息
- 平台/会话范围校验
- 文本与图片入库
- 功能编排（主随机回复 / 复读 / @处理）
- 发送结果

2. 定时流程
- 循环调度 tick
- 触发每日维护
- 触发时间戳回复

3. 分层调用原则
- 入口层：`main.py`
- 应用层：`app/*`
- 功能层：`features/*`
- 领域层：`domain/*`
- 基础设施层：`infra/*`

上层调用下层，同层不互相调用。

# 使用

1. 安装
- 将插件目录放入 AstrBot 插件目录。
- 在插件管理界面启用插件。

2. 关键配置
- 基础开关：`enable_passive_reply`
- 主随机回复：`reply_chance`、`text_reply_ratio`、`weighted_text_ratio`
- 复读：`enable_repeat`、`repeat_chance`
- API 图片：`enable_api_image`、`api_image_chance`、`api_image_url`
- @ 处理：`enable_at_handler` 与 `at_*_weight`
- 时间戳：`enable_timestamp_random_reply`、`timestamp_reply_probability`
- 私聊与群组范围：`allow_private_message`、`enabled_group_ids`、`disabled_group_ids`
- 存储维护：`weight_cleanup_threshold`、`cache_ttl_hours`、`local_keep_days`、`local_max_storage_mb`
- 远端：`remote_mode`、`remote_local_dir`、`remote_base_url`

3. 推荐最小配置
- 先只开启主随机回复，验证文本/图片入库。
- 再开启复读、API 图片和时间戳功能。
- 最后按需要开启群独立文本库与远端备份。

# 管理员命令

以下命令为管理员私聊机器人时可用（默认开启，可通过 `enable_admin_debug_commands` 关闭）。

1. `/random_reply_msg`
- 测试随机文本回复。

2. `/random_reply_img`
- 测试随机图片回复（含路径解析）。

3. `/repeat <文本>`
- 测试复读功能。

4. `/api_image`
- 测试 API 图片发送功能。

5. `/at_message [文本]`
- 测试 @ 处理动作选择逻辑。

6. `/timestamp_reply`
- 测试时间戳随机回复逻辑（按触发概率判定）。

7. `/clean_weight [阈值]`
- 清理低权重文本。
- 示例：`/clean_weight 0.3`
- 不传参数时默认使用 `0.2`。

8. `/clean_cache`
- 清理缓存目录中过期文件。

9. `/backup_data`
- 执行远端备份并清理（远端模式）或本地保留清理（本地模式）。

10. `/remote_backup_test`
- 测试远端备份连通性与推送结果统计。

# 关于

- 作者：maxshiro
- 插件名：randomreply_plugin
- 适配平台：QQ / Telegram（可通过配置扩展匹配）
- 许可证：见 `LICENSE`
- 问题反馈：建议附上配置片段、日志与复现步骤
