# Memory Supervisor
### 中文版本
[English Version](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/README.md)

这是一个轻量化的(大概只占30MB内存)，永远能够在窗口最前面的高度可视化实时内存监视工具

为Win11构建 (为了Arcylic毛玻璃效果) (在25H2 26200上经过验证)

---

## 展示内容

| 元素 | 含义 |
| --- | --- |
| 大百分数 | 物理内存占用占比 (`GlobalMemoryStatusEx`) |
| 横置条 | 图形可视化内存占用 |
| `x.xx / x.xx GB` | 已用/总内存真确值 |
| 拖拽位 | 用于调整窗口大小 |

## 启动要求

* Windows 11 (理论均可，仅在25H2, build 26200上测试)
* Python 3.8+ **如果直接用源代码运行才需要**

## 运行

双击↓↓应该不用教了罢（小声）

```
MemorySupervisor.exe
```

或者你也可以通过以下任意方式运行（需要python3.8+）:

```
run_silent.vbs        no console window      <- normal use
run.bat               with a console, useful for diagnostics
python memsup.py      direct
```

不直接运行.exe则需要如下环境: 一个在程序文件目录下的 `runtime\` , `launcher.ini`, `pythonw.exe`/`python.exe` 且已注册在
`PATH`上, 以及 `py` 启动器。 `launcher.ini` 会在第一次运行时自动生成/填入信息.

## 控制

| 操作 & 快捷键 | 效果 |
| --- | --- |
| **拖拽面板** | 移动窗口位置，且窗口位置会被记住 |
| **拖拽右下角拖拽位** | 调整面板大小 |
| **Ctrl + 鼠标滚轮** | 等比例放大/缩小 |
| **右键小托盘图标** | 进行例如各种预设大小调整、开机启动等的设置 |
| **Ctrl+Alt+F12** | 退出程序 |
| **Ctrl+Alt+F11** | 让程序一直前置 |

## 构建`.EXE`

```
python build_exe.py
```

详情请见英文版本[English Version](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/README.md)

## 运行测试

详情请见英文版本[English Version](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/README.md)

## 原理
[Click for Details](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/howItWorks.md)


## 除错
[Click for Details](https://github.com/ArisaYamatogi/MemorySupervisor/blob/main/troubleshooting.md)

## 为什么这小工具会存在
这要从宇宙大爆炸开始讲起（不是）。起因是作者换了台笔记本，内存缩小到只有
16G了，玩原神没事，但是一旦使用[Lunar Client](https://github.com/LunarClient)
启动mc就会经常莫名其妙几秒钟卡一下，又时不时直接爆内存闪退，甚至把分配的
内存大小调小也无济于事。鉴于用任务管理器实时查看内存占用过于不方便，且
无法在窗口最大化/无边框时保持前置，于是这个小工具就诞生了