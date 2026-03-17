# Random Reply Plugin TODO List

## 目标
构建一个随机回复机器人：
- 记录文本与图片消息
- 按概率随机回复文本或图片
- 图片读取采用本地优先、远端兜底
- 图片不可用时默认不回复

## 一、数据结构与目录
1. 创建目录结构：
- data/original_data/{platform}/{yyyyMMdd}/
- data/cache_media/
2. 准备本地数据文件：
- data/reply_msg_data.csv（消息内容,权重值,出现次数）
- data/reply_photo_data.csv（图片名称,出现次数,失效标记）
3. 原始消息json按日按群保存：
- {group_id}_messages.json

## 二、消息入库逻辑
1. 文本消息入库：
- 过滤包含图片/链接的消息
- 过滤长度 L >= n 的消息
- 新消息写入 reply_msg_data.csv
- 重复消息更新出现次数与权重
2. 图片消息入库：
- 按 平台_日期_群组id_用户id_时间戳_随机数.扩展名 命名
- 图片文件保存到 data/original_data/{platform}/{date}/
- 图片名称写入 reply_photo_data.csv
- 若已存在则仅更新出现次数

## 三、权重计算
1. 原始权重：
- W0 = 0.5 * (1 - ((L - 1) / (n - 1)))
2. 更新权重：
- Wn = W0 + (1 - W0) * (1 - exp(-alpha * (s - 1)))
3. 参数：
- n: 最大长度，要求 L < n
- alpha: 0-1，默认 0.1

## 四、图片读取与发送
1. 从 reply_photo_data.csv 随机选择图片名称（跳过失效标记=1）
2. 校验图片名称格式：
- 下划线分段数量合法
- 日期为 8 位数字
- 不合法则记录日志并判定不可用
3. 本地路径解析：
- data/original_data/{platform}/{date}/{image_name}
4. 本地命中则直接发送
5. 本地未命中则从远端（SMB/WebDAV）下载到 data/cache_media/
6. 下载成功后校验可读且大小 > 0，再发送
7. 远端也失败：
- 默认不回复
- 记录失败日志
- 连续失败达到阈值（默认 3 次）后标记失效

## 五、随机回复逻辑
1. 回复触发概率：1/REPLY_CHANCE
2. 类型选择：
- 文本概率 TEXT_REPLY_RATIO
- 图片概率 1 - TEXT_REPLY_RATIO
3. 文本选择：
- WEIGHTED_TEXT_RATIO 概率走加权随机
- 其余走均匀随机
4. 图片选择：
- 仅从可用图片中抽取
- 调用 resolve_photo_path() 解析路径
5. 空库保护：
- 文本库和图片库都为空：不回复
- 目标库为空：自动降级到可用库，否则不回复
6. 图片不可用保护：
- 解析失败/下载失败：默认不回复

## 六、并发与可靠性
1. csv并发安全：
- reply_msg_data.csv 与 reply_photo_data.csv 分别加文件锁
2. 原子写：
- 先写临时文件，再 rename 覆盖
3. 异常策略：
- 任一读写异常仅影响当前消息，不中断主流程
- 统一错误日志输出（含 platform/group/image_name）

## 七、定时任务
1. 每日 01:00：
- 推送前一天及更早 original_data 到远端存储
- 推送成功后清理本地过期数据
2. 每日 01:30：
- 清理 data/cache_media/ 中超过 24 小时的缓存文件

## 八、实现检查清单
- [ ] 完成文本入库、权重更新、去重逻辑
- [ ] 完成图片保存、图片名入库、失效标记更新逻辑
- [ ] 完成 resolve_photo_path()（本地优先 + 远端兜底）
- [ ] 完成随机回复总流程与空库保护
- [ ] 完成图片不可用默认不回复逻辑
- [ ] 完成 csv 文件锁与原子写
- [ ] 完成远端推送与缓存清理定时任务
- [ ] 完成关键路径日志与异常处理
