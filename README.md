# ClassPhoto Aligner / 照片名单对齐工具

> **说明：本项目由本人制作。本人不会任何编程，仅使用自然语言描述需求，由 DSH 完成实现。**

一个用于 Windows 的本地桌面工具：把**固定顺序的学籍照片队列**与 **Excel 名单**按位置对齐，并按学院、专业、班级批量导出为 `学号.jpg`。

核心规则：

> 第 N 张照片 = 当前名单第 N 条学生。

本工具不进行人脸识别，也不对照片做智能匹配，完全按照片队列位置与名单顺序对应。适合按班级分批处理大量学生证件照。

## 功能

- 照片按文件名自然排序，导入后顺序固定，界面不允许拖动照片。
- Excel 名单支持 `.xlsx` / `.xlsm` / `.xls`。
- 名单可选导入：学号、姓名、院系、班级、性别。
- 性别只显示 **男 / 女**；`M/F`、`male/female` 会自动归一。
- 每个班级一个班级框，点班级框同时筛选照片和名单；鼠标滚轮在班级框区域上下滚动可横向浏览班级。
- 选择院系后，班级框和班级号下拉只显示该院系的班级。
- 右侧名单根据窗口宽度自动切换为 **2 列 / 3 列**。
- 选到具体班级后，可在本班内拖动调整顺序、删除未到场学生。
- 鼠标移到照片卡片上会显示半透明放大镜和删除按钮；点击放大镜或直接双击照片打开非模态大图预览，点击预览窗口外的主程序区域、预览内空白处或“关闭”按钮都能关闭；删除立即从队列移除（不删源文件，可撤销）。
- 左侧照片右键也可立即删除照片，不再二次确认；只从队列移除，不删除源文件，可撤销。
- 右侧名单右键可“添加学生”：学号必填，姓名和性别可空白；新学生追加到名单最后一位，并归入当前院系/班级。
- 右侧名单右键可删除未到场，或移到名单/本班/筛选结果的开头或末尾；支持 Shift 多选批量移动，批量项保持原选中顺序整体移动，并保持选中、支持撤销。
- 照片选中后按 `Delete` 删除；名单姓名选中后按 `End` 移到末尾。
- 工具栏“重做”后的“清空”按钮可一次清空所有导入照片和名单，不删除源文件，并重置撤销/重做历史。
- 菜单“编辑 → 自定义快捷键…”可修改照片删除、名单删除、移到末尾、上移/下移、撤销/重做、导出的快捷键。
- 按班级导出：`导出路径/学院/班级/学号.jpg`，班级文件夹只使用班级代码。
- 每导出一个班，班级框显示 **✓ 已导出**，标记会保存；某院系所有班级都导出后，院系下拉框会显示 **（已全部导出）**。
- 本班导出成功后，自动选中当前院系的下一个班级，便于连续处理。
- 后台复制、进度、取消、断点续跑、CSV 日志、JSON 汇总、按日志撤销。
- 右上角主题按钮按“浅色 → 深色 → 纯黑 → 浅色”循环切换，选择会保存。
- 窗口和任务栏使用 `app/app.ico`（照片叠放 + 名单图标）。
- 4000+ 张照片使用缩略图虚拟化，不会一次性解码全部图片。

## 照片路径如何识别学院/专业/班级

导入照片时选择**根目录**，工具会递归扫描子文件夹。示例：

```text
学籍机械/机械26211/IMG_0001.JPG   -> 机械工程学院 / 机械 / 26211
北校区/26621/IMG_0002.JPG         -> 汽车工程学院 / 汽车 / 26621
学籍262401班/IMG_0003.JPG          -> 机械工程学院 / 机械 / 262401
```

路径里的“机械”“北校区”等简称，会在导入名单后用相同班级代码对应的完整院系名校正。专业信息仅用于识别，不再进入最终导出路径；输出只保留“学院/班级/学号.jpg”。

## 快速开始

要求：Windows 10/11、Python 3.13+（64 位）。

```powershell
git clone https://github.com/lee31424/classphoto-aligner.git
cd classphoto-aligner

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

.\run.bat          # 正常启动，不显示控制台
.\run_debug.bat    # 带控制台启动，便于排错
```

`run.bat` 会优先使用 `.venv\Scripts\pythonw.exe`，其次使用 `pyw -3` / `pythonw`。

## 使用环境

- 操作系统：Windows 10 / Windows 11，64 位
- Python：3.13 或更高版本，64 位
- 图形界面：PySide6 6.12.0 / Qt 6.12
- Excel 读取：openpyxl 3.1.5（`.xlsx/.xlsm`）、xlrd 2.0.2（`.xls`）
- 建议分辨率：1920×1080；最低可用约 1280×720
- 内存：建议 4 GB 以上，处理 4000+ 张缩略图时更流畅
- 磁盘：需要能存放导出照片和缩略图缓存；建议预留至少与源照片总大小相当的空间
- 权限：普通用户即可，不需要管理员权限；导出目录、缓存目录和日志目录需要可写
- 照片格式：`.jpg` / `.jpeg` / `.jpe`
- 运行方式：本地桌面程序，不需要联网；不依赖数据库或 Web 服务

## 使用流程

1. 导入照片根目录。
2. 导入 Excel 名单，确认学号、姓名、院系、班级、性别列。
3. 点班级框选择班级。
4. 在本班内拖动名单、删除未到场学生。
5. 在顶部填写导出路径；右侧“打开导出文件夹”可直接打开当前导出目录（选了班级会优先打开该班文件夹）。
6. 点窗口**右下角**的 **“修改并导出本班”**，立即导出当前班；按钮左侧显示当前选中的班号，字号约为按钮高度的 2/3。
   班号左侧的 **“需核对”** 按钮执行同样的导出流程，但班级文件夹名追加“ 需核对”，例如 `机械工程学院\26212 需核对`。
   “需核对”左侧的 **“有闭眼”** 按钮同样导出，但班级文件夹名追加“ 有闭眼”，例如 `机械工程学院\26212 有闭眼`。
7. 接着选下一个班级。

照片数、名单人数、剔除数和差值显示在窗口底部。当前班照片数与名单人数不一致时，“修改并导出本班”和“导出到新文件夹”会一起禁用，需要先处理差值。

右键操作：

- 照片右键：**删除照片（仅从队列移除）**。
- 名单右键：**删除未到场**、**移到本班末尾 / 移到名单末尾**。
- 以上操作都支持 `Ctrl+Z` 撤销。

## 输出结构

```text
导出路径/
└─ 机电工程学院/
   └─ 2659A/
      ├─ 2621101.jpg
      └─ 2621102.jpg
```

照片输出目录里**只放照片**，不会生成 CSV、JSON 或其他日志文件。

导出日志统一写到：

```text
H:\PhotoRosterTool\logs\export_logs\<run_id>\
├─ rename_plan_*.csv
├─ rename_log_*.csv
└─ rename_summary_*.json
```

- 源照片只读，不会被改名、移动或删除。
- 输出目录必须位于照片源目录之外。
- 已存在且大小一致的目标文件会跳过，可用于断点续跑。
- 撤销只删除日志中状态为 `ok` 且大小校验一致的文件，撤销日志也写到 `logs/export_logs`。

## 项目结构

```text
app/
  main.py         界面、筛选、班级框、导出流程
  models.py       照片/名单模型、班级排序
  grouping.py     路径中的学院/专业/班级解析
  excel_io.py     .xlsx / .xlsm / .xls 读取
  dialogs.py      Excel 列映射、未到场恢复对话框
  delegates.py    照片卡片、名单卡片绘制
  exporter.py     预检、复制线程、CSV/JSON 日志、撤销
  thumbnails.py   缩略图懒加载与缓存
  widgets.py      自适应名单网格、拖放处理
  tests/smoke_test.py
```

## 测试

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
python app\tests\smoke_test.py
```

测试会生成临时照片和 Excel，验证导入、性别、班级筛选、两列/三列布局、本班拖动、右键删除/移动、按班级导出、断点续跑、撤销、缩略图与 4000 项虚拟化。

## 说明

- 本项目是本地 Windows 桌面工具，不是 Web 服务。
- 照片顺序在导入时固定；只有名单可以调整。
- 程序使用 `QSettings` 保存窗口和导出偏好；`cache/`、`logs/`、`output/`、`testdata*/`、`.venv/` 已加入 `.gitignore`。

## 许可证

本项目采用 **GNU General Public License v3.0（GPL-3.0）** 开源许可。

```text
Copyright (C) 2026 lee31424

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
```

完整条款见 [LICENSE](LICENSE)，或访问 <https://www.gnu.org/licenses/gpl-3.0.html>。
