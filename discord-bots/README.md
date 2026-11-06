# Discord 角色 Bot 源码快照

2026-11-06：35 只角色 Bot 的公开脱敏源码。来自当时运行容器中的实际文件，包含已挂载的专用代码，而非仅有旧的共同基础包。原仓库的网站项目保持在仓库根目录，本目录独立存放 Bot 相关内容。

包含聊天核心、角色设定、表情/界面资源、世界与游戏模块、媒体模块、权限控制、迁移脚本和依赖记录。角色专用的私聊、语音、生图、代答、主人代理和记忆实现按各自快照保留。真人身份及服务器绑定、模型凭据、私有上游地址使用占位配置；数据库、聊天记录、学习样本、记忆内容、历史备份和密钥不公开。

## 角色目录

| 角色 | 标识 | 框架 | 目录 |
|---|---|---|---|
| Mordred / 莫德雷德 | `mordred` | legacy | [源码](bots/mordred/) |
| 芭万·希 | `tristan` | lite | [源码](bots/tristan/) |
| Artoria Caster / 阿尔托莉雅·卡斯特 | `caster` | legacy | [源码](bots/caster/) |
| Aesc / 梣 | `aesc` | legacy | [源码](bots/aesc/) |
| Illya / 伊莉雅 | `illya` | legacy | [源码](bots/illya/) |
| Morgan / 摩根 | `morgan` | legacy | [源码](bots/morgan/) |
| 小鲸 | `whale` | lite | [源码](bots/whale/) |
| 哈基咪娘 | `hajimi` | lite | [源码](bots/hajimi/) |
| GPT娘 | `gpt` | lite | [源码](bots/gpt/) |
| 小克 | `xiaoke` | lite | [源码](bots/xiaoke/) |
| 类脑娘 | `classbrain` | lite | [源码](bots/classbrain/) |
| 小樱 | `sakura` | lite | [源码](bots/sakura/) |
| 黑贞德 | `jalter` | lite | [源码](bots/jalter/) |
| 贞德 | `jeanne` | lite | [源码](bots/jeanne/) |
| 月见里结月 | `yuzuki` | lite | [源码](bots/yuzuki/) |
| 玛丽安 | `marian` | lite | [源码](bots/marian/) |
| 朽木冬子 | `touko` | lite | [源码](bots/touko/) |
| 伊蕾娜 | `elaina` | lite | [源码](bots/elaina/) |
| 七海千秋 | `chiaki` | lite | [源码](bots/chiaki/) |
| 明日香 | `asuka` | lite | [源码](bots/asuka/) |
| 绫波丽 | `rei` | lite | [源码](bots/rei/) |
| 时崎狂三 | `kurumi` | lite | [源码](bots/kurumi/) |
| 薇尔莉特 | `violet` | lite | [源码](bots/violet/) |
| 阿尔托莉雅（Saber） | `artoria` | lite | [源码](bots/artoria/) |
| 夜刀神十香 | `tohka` | lite | [源码](bots/tohka/) |
| 鸢一折纸 | `origami` | lite | [源码](bots/origami/) |
| 四系乃 | `yoshino` | lite | [源码](bots/yoshino/) |
| 五河琴里 | `kotori` | lite | [源码](bots/kotori/) |
| 冬马和纱 | `kazusa` | lite | [源码](bots/kazusa/) |
| 小木曾雪菜 | `setsuna` | lite | [源码](bots/setsuna/) |
| 佐助 | `sasuke` | lite | [源码](bots/sasuke/) |
| 鸣人 | `naruto` | lite | [源码](bots/naruto/) |
| 星宫六喰 | `mukuro` | lite | [源码](bots/mukuro/) |
| 远坂凛 | `rin` | lite | [源码](bots/rin/) |
| 露维亚瑟琳塔·艾德费尔特 | `luvia` | lite | [源码](bots/luvia/) |

## 使用

先阅读对应目录的 README。公开版本是可审阅的源码和配置模板，不是包含凭据、数据库和全部基础镜像的生产环境备份。请保留现有服务器上的私有配置与数据；传统框架仍需其原配套服务。

每个目录的 `snapshot-manifest.json` 可核对文件完整性。`tools/verify_snapshot.py` 检查公开文件散列、35 角色覆盖、Python 语法及不应提交的文件类型。原组件许可证保留在各自目录。
