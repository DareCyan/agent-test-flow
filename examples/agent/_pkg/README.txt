shopping-agent-v2 示例安装包
============================

内容
----
  agent.py           示例智能体（占位实现，仅标准库）
  requirements.txt   依赖声明（示例为空）
  manifest.json      包元信息（entry / runtime / 能力声明）
  README.txt         本文件
  legacy_init.sh     旧版初始化脚本（install.json 里该步骤声明 skip=true）

用途
----
r1「智能体接入」左侧槽位上传该 .zip，用于演示上传交互。
本包刻意做到"内容自洽"：install.json 的 verify 步骤断言 {workspace}/agent.py
存在，而本包确实带 agent.py，所以解压后该断言能通过。

注意
----
- 这是占位实现，不连接任何模型、不访问网络。
- 后端只记录上传时的文件名与大小（binary_stored: false），不解析包内容；
  换成真实安装包不会改变流程行为。
- 真实接入时，把本包替换为被测智能体自己的安装包即可。

自检
----
  python agent.py --info      # 打印包信息
  python agent.py --health    # 检查 8000 端口是否在监听
