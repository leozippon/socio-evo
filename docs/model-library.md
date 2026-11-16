# 模型库与 GPU 推理

课题组在 Office 使用 `model` 工具获取预训练模型。模型与参数量由居民根据研究问题、对照设计和可用算力自主选择，没有模型名或参数量白名单；文中的示例仅说明用法，不限定研究选型。模型库按照当前模拟时间选择 Hugging Face 的历史 commit；居民不能自行把截止日期改到未来。下载返回固定版本的 `model_id`，后续推理和训练都可以引用同一份权重。

## 找到并下载模型

以下为模型工具的参数，不是在 shell 中执行的 Python 函数。将占位符替换为研究关键词和自主选定的仓库：

```json
{"action":"search","query":"<research keywords>"}
```

```json
{"action":"info","repo_id":"<chosen repo>"}
```

```json
{"action":"download","repo_id":"<chosen repo>"}
```

检查返回的 commit、版本时间和来源说明，再保存返回的 `model_id`。使用 `{"action":"list"}` 可以查阅课题组已下载的版本。指定 `revision` 时必须提供完整 commit，且该版本不能晚于模拟时间。可以选择其他符合这些条件的模型；能否执行取决于模型与运行库的兼容性及实际资源需求。当前支持公开、无需授权访问的模型，不需要提供 Hugging Face Token。私有仓库和 gated 模型尚未开放；需要额外远程 Python 代码的模型也不在首版支持范围。

下载的完整权重保存在宿主模型缓存，不进入论文 Git 历史。仅本实验已登记的版本会以只读目录 `/models/<model_id>` 提供给实验容器。下载失败不会把半个模型登记为可用。下载超时默认一小时，与默认十分钟的实验命令/推理超时分开配置。模型登记和来源记录保存在 `/records/models.json`，随科研检查点恢复。

## 用 vLLM 生成

```json
{"action":"generate","model_id":"<下载返回的 model_id>","prompts":["用一句话解释信息检索。","What is a retrieval-augmented language model?"],"chat":true,"temperature":0,"seed":0,"max_tokens":96,"max_model_len":4096}
```

`prompt` 用于单条输入，`prompts` 用于批量输入，两者选一个。当前每批最多 8 条，更多输入需显式分批。默认 `chat=true`，系统应用模型自己的聊天模板；基础模型或文本续写实验使用 `chat=false`。`max_tokens` 是每条输出的上限，`max_model_len` 是输入加输出的上下文容量。超出容量会明确报错，不静默截断研究输入。

此工具启动独立的离线 vLLM 进程，固定使用实验卡，即宿主 GPU 1。它与本课题组的 shell 实验串行，执行完或取消后释放 GPU。它不会使用驱动居民的 GPU 0，也不会把居民的 shell 命令交给宿主执行。每次生成记录模型身份、参数、输出和执行状态；是否得到有用的科学结果仍需设计对照实验。

## 用 Transformers 训练或推理

在 `shell` 工具中使用下载返回的路径。容器内的 `cuda:0` 对应宿主 GPU 1：

```python
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

path = '/models/<下载返回的 model_id>'
tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
model = AutoModelForCausalLM.from_pretrained(
    path, local_files_only=True, trust_remote_code=False,
    dtype='auto', device_map='cuda:0',
)
inputs = tokenizer.apply_chat_template(
    [{'role': 'user', 'content': '用一句话解释信息检索。'}],
    add_generation_prompt=True, return_tensors='pt', return_dict=True,
).to('cuda:0')
with torch.inference_mode():
    outputs = model.generate(**inputs, max_new_tokens=64, do_sample=False)
print(tokenizer.decode(outputs[0, inputs['input_ids'].shape[1]:], skip_special_tokens=True))
```

微调时加载同样的本地路径，把新检查点和实验代码保存到 `/research`。模型库原始权重为只读。自定义 `.pt` 字典不等于标准 Hugging Face 模型目录，不能直接交给 vLLM 加载。研究容器仍不直接联网，`from_pretrained('在线仓库名')` 不能替代模型库下载。

## 时间与复现边界

模型版本按 commit 时间筛选，并记录下载文件的哈希。Zenith 当前配置使用 `https://hf-mirror.com` 获取 Hugging Face 内容，实际 endpoint 会写入来源记录；已验收的模型快照与官方 commit 和权重 SHA-256 一致。当前搜索排序和可访问性不等于过去的搜索结果，commit 时间也不能证明当时已公开发布；模型库不把它称为严格的历史公开性证明。模型权重版本与现代推理软件版本分别记录，避免把现代运行环境误称为完整的历史环境。

已经收到旧模型示例的居民会在科研设施开放后收到一次更正通知。原 `records/models-capability.json` 保留为历史，修订说明保存到 `records/models-help-v2.json`，随检查点恢复且不重复通知。新实验直接使用修订后的说明，只发送首次能力通知。

部署状态、实际下载与 GPU 验收结果由[运行说明](../ops/research/README.md)记录。当前实验的环境变更须保留原记录和续跑来源，不应被当作从第一天起条件完全一致的实验。
