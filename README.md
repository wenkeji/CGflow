# CGflow

CGflow 用来创建、提交、检查、下载和分析 GROMACS 粗粒化任务。代码和结果分开管理：

| 类型 | 推荐位置 | 说明 |
| --- | --- | --- |
| 代码仓库 | `/home/wenke/CGflow` | 只放程序、模板和配置 |
| SDS 结果 | `/home/wenke/SDS_results` | 当前 SDS 相关任务 |
| 其他体系结果 | `/home/wenke/<name>_results` | 例如 CTAB、SLES 等 |

> 在 VS Code 中查看渲染效果：按 `Ctrl+Shift+V` 打开 Markdown Preview。

## 目录

- [快速开始](#快速开始)
- [结果目录规则](#结果目录规则)
- [Alias](#alias)
- [远程传输](#远程传输)
- [命令速查](#命令速查)
- [JSON 配置示例](#json-配置示例)
- [目录结构](#目录结构)

## 快速开始

### 1. 创建任务

```bash
mkdir -p /home/wenke/SDS_results/c1c1_scale_all_beads_run
cd /home/wenke/SDS_results/c1c1_scale_all_beads_run
create --config /home/wenke/CGflow/configs/c1c1_examples.json
```

### 2. 提交、检查、下载、分析

```bash
submit experiment.json
check experiment.json
download experiment.json
analyze experiment.json
```

### 3. 只处理单个任务组

```bash
submit st_regular/task_group.json
check st_regular/task_group.json
download st_regular/task_group.json
analyze st_regular/task_group.json
```

## 结果目录规则

`create` 保留当前工作目录。运行 `create --config input.json` 时，会直接把 `experiment.json`、`st_*`、`cmc_*` 生成在当前目录，不会再自动套一层 `Tini_Na_日期时间/`。

如果你想把结果生成到某个新子目录，才使用 `--d`：

| 体系 | 推荐命令 |
| --- | --- |
| 当前目录直接生成 | `create --config input.json` |
| 在指定根目录下新建子目录 | `create --config input.json --output-root /home/wenke/SDS_results --d my_run` |
| 新表面活性剂结果目录 | `create --config input.json --output-root /home/wenke/<name>_results --d my_run` |

示例：

```bash
create --config /home/wenke/CGflow/configs/c1c1_examples.json \
  --output-root /home/wenke/NEW_SURFACTANT_results \
  --d my_new_run
```

## Alias

建议放在 `~/.bashrc`：

```bash
alias create="PYTHONPATH=/home/wenke/CGflow conda run -n CGflow python -m workflow.create"
alias submit="PYTHONPATH=/home/wenke/CGflow conda run -n CGflow python -m workflow.submit"
alias check="PYTHONPATH=/home/wenke/CGflow conda run -n CGflow python -m workflow.check"
alias download="PYTHONPATH=/home/wenke/CGflow conda run -n CGflow python -m workflow.download"
alias analyze="PYTHONPATH=/home/wenke/CGflow conda run -n CGflow python -m workflow.analyze"
```

修改后执行：

```bash
source ~/.bashrc
```

## 远程传输

提交和下载的文件传输只使用 `rsync + ssh`：

| 方向 | 工具 | 说明 |
| --- | --- | --- |
| 本地上传到 HPC | `rsync -avP` | 上传任务输入包、提交脚本等 |
| HPC 下载到本地 | `rsync -avP --append-verify` | 下载 `*.results.tar`，支持断点续传 |

Paramiko 只用于远程执行命令，例如 `mkdir`、`bsub`、状态检查和远程文件探测；不再用于 SFTP 文件传输。

远程任务目录会保留实验目录名和实验内相对路径，避免不同实验的同名任务互相覆盖：

```text
本地:
/home/wenke/SDS_results/Tini_Na_C1C1/cmc_regular/c1c1_x1

远程:
/home/cadmol/fi2928/Tini_Na_C1C1/cmc_regular/c1c1_x1
```

例如 `regular_Na_C1C1` 下的同名任务会提交到：

```text
/home/cadmol/fi2928/regular_Na_C1C1/cmc_regular/c1c1_x1
```

## 命令速查

| 命令 | 用途 | 常用输入 |
| --- | --- | --- |
| `create` | 创建本地任务目录和提交脚本 | JSON 配置、scan/bead 参数 |
| `submit` | 用 rsync 上传并提交到 HPC | `experiment.json`、`task_group.json`、`hpc_submit_info.json` |
| `check` | 检查远程状态 | `experiment.json`、`task_group.json`、`hpc_submit_info.json` |
| `download` | 用 rsync 下载并解包结果 | `experiment.json`、`task_group.json`、`hpc_submit_info.json` |
| `analyze` | 分析 ST 和 CMC 结果 | `experiment.json`、`task_group.json`、`hpc_submit_info.json` |

`submit`、`check`、`download`、`analyze` 推荐直接传 JSON 元数据：

| 输入形式 | 解析目标 |
| --- | --- |
| `experiment.json` | 实验下所有任务 |
| `st_regular/task_group.json` | 任务组下所有任务 |
| `cmc_regular/c1c1_x1/hpc_submit_info.json` | 单个任务 |

只接受 JSON 元数据文件作为输入；不要传实验名、任务组目录名或任务目录名。

### create

用 JSON 创建完整实验：

```bash
cd /home/wenke/SDS_results/c1c1_scale_all_beads_run
create --config input.json
```

不用 JSON 时，也可以直接指定任务类型：

```bash
create --scan st --bead regular --na Tini_Na --output-root /home/wenke/SDS_results --d st_regular
create --scan cmc --bead regular --na Tini_Na --output-root /home/wenke/SDS_results --d cmc_regular
create --scan all --bead all --na regular_Na --output-root /home/wenke/SDS_results --d regularNa_run
```

| 参数 | 说明 |
| --- | --- |
| `--config` | JSON 实验配置文件 |
| `--output-root` | 结果输出根目录；默认是当前目录 |
| `--d` | 可选；指定后会在 `--output-root` 下创建这个子目录 |
| `--scan` | `st`、`cmc` 或 `all` |
| `--bead` | `regular`、`small`、`tini` 或 `all` |
| `--na` | `Tini_Na` 或 `regular_Na` |

### submit / check / download

```bash
submit experiment.json
check experiment.json
download experiment.json
```

上面的命令应在实验目录中运行，例如 `/home/wenke/SDS_results/c1c1_scale_all_beads_run`。也可以传绝对路径，例如 `/home/wenke/SDS_results/c1c1_scale_all_beads_run/experiment.json`。不再支持只传实验名或目录名。

`download` 成功后默认删除远程任务目录，并清理空的远程任务组父目录。

如果需要保留远程目录：

```bash
download --keep-remote experiment.json
```

### analyze

```bash
analyze experiment.json
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--edr` | `eq.edr` | ST 分析使用的能量文件名 |
| `--begin` | `10000` | 传给 `gmx energy -b` 的起始时间，单位 ps |
| `--gmxrc` | 代码默认值 | GMXRC 路径 |

## JSON 配置示例

三种 C bead 都跑；ST 只跑 200 和 500；CMC 不改结构，只改力场：

```json
{
  "name": "c1c1_scale_all_beads",
  "na_model": "Tini_Na",
  "bead_groups": ["regular", "small", "tini"],
  "scans": ["st", "cmc"],
  "forcefield": {
    "parameter": "C1-C1",
    "scale_factors": ["1/3", "2/3", "1"]
  },
  "st": {
    "n_surfs": [200, 500]
  },
  "cmc": {
    "enabled": true
  }
}
```

直接指定 epsilon 数值：

```json
{
  "forcefield": {
    "parameter": "W-C1",
    "epsilons": [0.5, 1.0, 2.0]
  }
}
```

`parameter` 可以写 `C1-C1`、`W-C1` 这类非键参数。

如果 JSON 中不写 `forcefield`，则不会做力场参数扫描。CMC 任务会直接生成在 `cmc_regular`、`cmc_small`、`cmc_tini`。

如果 JSON 中写了 `forcefield`，CMC 第一层仍然是 bead 任务组，第二层才是具体力场参数，例如：

```text
cmc_regular/
  c1c1_x0p333/
  c1c1_x0p667/
  c1c1_x1/
```

## 目录结构

模型输入放在代码仓库中：

```text
/home/wenke/CGflow/model/{Tini_Na,regular_Na}/{regular,small,tini}/{st,cmc}
```

结果目录示例：

```text
/home/wenke/SDS_results/
  c1c1_scale_all_beads_run/
    experiment.json
    st_regular/
    st_small/
    st_tini/
    cmc_regular/
    cmc_small/
    cmc_tini/
```

主要代码入口：

```text
workflow/create/    创建任务
workflow/submit/    提交任务
workflow/check/     检查状态
workflow/download/  下载并解包结果
workflow/analyze/   分析 ST 和 CMC
```
