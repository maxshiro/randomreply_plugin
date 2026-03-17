# 模块架构说明

本文档说明当前插件的目录分层、各模块职责以及推荐的扩展方式。

## 总体分层

当前代码按以下层次组织：

1. 入口层
- `main.py`
- 职责：AstrBot 插件注册、事件绑定、依赖装配、生命周期管理。
- 约束：不直接处理 CSV、图片、远端存储等细节。

2. 应用层
- `app/message_processor.py`
- `app/feature_orchestrator.py`
- `app/scheduler.py`
- 职责：编排业务流程，决定何时调用哪一个功能模块。
- 约束：不直接读写底层文件，统一通过基础设施层完成。

3. 功能层
- `features/random_reply.py`
- `features/repeat.py`
- `features/at_message.py`
- `features/api_image.py`
- 职责：实现一个单一功能的选择逻辑或行为逻辑。
- 约束：不负责调度，不决定生命周期，不直接管理插件状态。

4. 领域层
- `domain/message.py`
- `domain/randomization.py`
- `domain/weight_calculator.py`
- 职责：沉淀纯业务规则与纯算法。
- 约束：不依赖 AstrBot、文件系统或网络。

5. 基础设施层
- `infra/repo/*`
- `infra/file_lock/*`
- `infra/media/*`
- `infra/remote_storage/*`
- 职责：处理文件、锁、CSV、JSON、图片保存与远端访问等 I/O 细节。
- 约束：只提供能力，不负责上层流程判断。

## 调用方向

只允许上层调用下层，不允许同层互相穿透。

推荐调用链：

- `main.py` -> `app/*`
- `app/*` -> `features/*`
- `app/*` -> `infra/*`
- `features/*` -> `domain/*`
- `features/*` -> `infra/*`
- `infra/*` 不反向依赖 `app/*` 或 `main.py`

不推荐：

- `features/*` 直接调用 `app/*`
- `domain/*` 依赖 `astrbot.api`
- `main.py` 直接写 CSV 或直接实现随机算法

## 入口层说明

### `main.py`
职责：
- 创建插件实例
- 初始化目录
- 装配仓储、图片服务、远端存储、功能模块、调度器
- 接收 AstrBot 消息事件
- 启动定时循环

你后续新增功能时，优先在这里“注册和装配”，不要在这里写大量业务逻辑。

## 应用层说明

### `app/message_processor.py`
职责：
- 从 `AstrMessageEvent` 提取上下文
- 校验平台、群组、私聊、命令消息等
- 处理文本与图片入库
- 将事件转交给 `feature_orchestrator`

适合放在这里的逻辑：
- 是否允许当前会话触发功能
- 是否应该入库
- 如何从 event 提取群号、用户号、是否 @ 机器人

### `app/feature_orchestrator.py`
职责：
- 协调主随机回复、复读、API 图片、@处理、时间戳触发
- 决定当前应该执行哪个功能

适合放在这里的逻辑：
- 多功能之间的优先级和选择策略
- 时间戳功能中不同动作的组合

### `app/scheduler.py`
职责：
- 每日 01:00 低权重清理
- 每日 01:00 本地保留或远端推送
- 每日 01:30 缓存清理
- 每分钟秒数为 0 的时间戳触发逻辑

适合放在这里的逻辑：
- 调度时机
- 主动消息发送的编排
- 定时动作串联

## 功能层说明

### `features/random_reply.py`
职责：
- 主随机回复逻辑
- 文本池/图片池选择
- 文本加权与均匀随机
- 图片失效计数与失效标记

### `features/repeat.py`
职责：
- 复读功能的独立概率判定

### `features/api_image.py`
职责：
- API 图片功能的独立概率判定
- 实际图片获取调用交给 `infra/media/image_service.py`

### `features/at_message.py`
职责：
- 机器人被 @ 时在多个动作之间按权重选择
- 动作包括：主随机回复、复读、API 图片、固定消息

如果以后你新增“表情包回复”“固定短语池回复”“根据时段切换回复风格”，优先新增一个新的 `features/*.py`。

## 领域层说明

### `domain/message.py`
职责：
- 定义消息处理过程中使用的上下文数据结构

### `domain/randomization.py`
职责：
- 概率命中
- 权重选择
- 通用随机算法

### `domain/weight_calculator.py`
职责：
- 文本权重计算公式
- 权重更新公式

以后所有“纯公式”“纯判定”“纯随机策略”，优先放到 `domain`。

## 基础设施层说明

### `infra/repo/text_repo.py`
职责：
- 文本库 CSV 的读写
- 群独立文本库路径管理
- 低权重清理
- 全局库到群库迁移

### `infra/repo/photo_repo.py`
职责：
- 图片库 CSV 的读写
- 图片失效标记维护

### `infra/repo/raw_message_repo.py`
职责：
- 原始消息 JSON 存储
- 历史群组发现

### `infra/file_lock/lock.py`
职责：
- 文件锁封装
- 提供并发安全保障

### `infra/media/image_service.py`
职责：
- 图片消息保存
- 图片大小限制
- 图片路径解析
- API 图片内容解析
- 本地优先 / 远端兜底

### `infra/remote_storage/*`
职责：
- 远端存储抽象与不同实现

当前实现包括：
- `base.py`：抽象接口与空实现
- `local_copy.py`：本地目录映射
- `webdav_http.py`：WebDAV/HTTP
- `factory.py`：按配置创建远端存储实例

以后新增 SMB、S3、OSS 等方式时，推荐新增一个文件并接入 `factory.py`。

## 新功能扩展建议

### 新增一个“功能”
推荐步骤：
1. 在 `features/` 下新增一个独立模块
2. 在需要时把通用算法抽到 `domain/`
3. 在 `app/feature_orchestrator.py` 中接入该功能
4. 在 `main.py` 中完成依赖装配
5. 在 `_conf_schema.json` 中增加配置项

### 新增一种“远端存储”
推荐步骤：
1. 在 `infra/remote_storage/` 下新增实现文件
2. 实现 `fetch()` 与 `push()`
3. 修改 `factory.py` 注入新模式
4. 在 `_conf_schema.json` 中加入对应配置

### 新增一种“定时任务”
推荐步骤：
1. 在 `app/scheduler.py` 中加入新的时间判断
2. 需要复用的文件操作下沉到 `infra/`
3. 需要复用的功能逻辑下沉到 `features/`

## 维护建议

1. 如果一个逻辑需要访问 AstrBot 事件对象，优先放应用层。
2. 如果一个逻辑只是在多个候选动作里选一个，优先放功能层。
3. 如果一个逻辑是公式、概率或纯规则，优先放领域层。
4. 如果一个逻辑涉及 CSV、JSON、文件、网络、路径，优先放基础设施层。
5. 当 `main.py` 再次变长时，不要继续堆逻辑，优先继续往下层拆。

## 当前目录结构

```text
randomreply_plugin/
├── main.py
├── _conf_schema.json
├── CHANGELOG.md
├── ARCHITECTURE.md
├── app/
│   ├── message_processor.py
│   ├── scheduler.py
│   └── feature_orchestrator.py
├── features/
│   ├── random_reply.py
│   ├── repeat.py
│   ├── at_message.py
│   └── api_image.py
├── domain/
│   ├── message.py
│   ├── randomization.py
│   └── weight_calculator.py
└── infra/
    ├── file_lock/
    │   └── lock.py
    ├── media/
    │   └── image_service.py
    ├── remote_storage/
    │   ├── base.py
    │   ├── factory.py
    │   ├── local_copy.py
    │   └── webdav_http.py
    └── repo/
        ├── photo_repo.py
        ├── raw_message_repo.py
        └── text_repo.py
```
