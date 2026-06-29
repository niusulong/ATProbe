ATProbe — 串口 AT 命令自动化测试工具
========================================

【快速开始】
1. 解压本压缩包到任意目录（如 D:\ATProbe）
2. 双击 ATProbe.exe 启动图形界面
3. 在「环境配置」页填你的串口（如 COM5:115200:8N1）

【命令行用法】（可选，给会命令行的工程师）
  atprobe-cli.exe list cases
  atprobe-cli.exe run examples\testcases\ntp\ntp-updatetime_query.yaml --port COM5:115200
  atprobe-cli.exe --version

【自定义】
- 改用例：编辑 examples\testcases\ 下的 .yaml 文件
- 改默认配置：把 atprobe.yaml.template 复制为 atprobe.yaml，放在
  ATProbe.exe 同级目录，按需修改后重启程序
- 运行日志在 logs\，HTML 报告在 reports\

【系统要求】
- Windows 10/11 x64
- 无需安装 Python，本程序已内置运行环境
- 首次运行若被杀毒软件拦截，请加白名单（程序未做代码签名，属正常现象）

【版本】见 ATProbe.exe「关于」菜单或运行 atprobe-cli.exe --version
