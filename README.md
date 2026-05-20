# CGflow

CGflow 用来创建、提交、检查、下载和分析 GROMACS 粗粒化任务。

## 快速开始

```bash
mkdir -p /home/wenke/SDS_results/c1c1_scale_all_beads_run
cd /home/wenke/SDS_results/c1c1_scale_all_beads_run
create --config /home/wenke/CGflow/configs/c1c1_examples.json

submit experiment.json
check experiment.json
download experiment.json
analyze experiment.json
```

也可以只处理一个任务组或单个任务：

```bash
submit st_regular/task_group.json
check cmc_regular/c1c1_x1/hpc_submit_info.json
```

## 命令

所有工作流命令都基于 JSON 文件。

| 命令 | 用途 | 输入 |
| --- | --- | --- |
| `create` | 创建本地任务目录和提交脚本 | 实验配置 JSON |
| `submit` | 上传并提交到 HPC | 元数据 JSON |
| `check` | 检查远程状态 | 元数据 JSON |
| `download` | 下载并解包结果 | 元数据 JSON |
| `analyze` | 分析 ST 和 CMC 结果 | 元数据 JSON |

`submit`、`check`、`download`、`analyze` 接受：

| JSON | 作用 |
| --- | --- |
| `experiment.json` | 整个实验 |
| `task_group.json` | 一个任务组 |
| `hpc_submit_info.json` | 单个任务 |

### create

```bash
create --config input.json
create --config input.json --output-root /home/wenke/SDS_results --d my_run
```

`create --config input.json` 会在当前目录生成 `experiment.json`、`st_*`、`cmc_*`。需要在指定根目录下新建结果目录时，用 `--output-root` 和 `--d`。

### download

```bash
download experiment.json
download --keep-remote experiment.json
```

默认下载成功后会删除远程任务目录。需要保留远程目录时加 `--keep-remote`。

### analyze

```bash
analyze experiment.json
analyze experiment.json --begin 10000 --edr eq.edr
```

## JSON 配置示例

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

也可以直接指定 epsilon：

```json
{
  "forcefield": {
    "parameter": "W-C1",
    "epsilons": [0.5, 1.0, 2.0]
  }
}
```

常用配置文件在：

```text
configs/c1c1_examples.json
configs/wc1_examples.json
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

```bash
source ~/.bashrc
```

## 路径

```text
代码仓库: /home/wenke/CGflow
模型输入: /home/wenke/CGflow/model/{Tini_Na,regular_Na}/{regular,small,tini}/{st,cmc}
SDS 结果: /home/wenke/SDS_results
其他结果: /home/wenke/<name>_results
```

结果目录示例：

```text
/home/wenke/SDS_results/c1c1_scale_all_beads_run/
  experiment.json
  st_regular/
  st_small/
  st_tini/
  cmc_regular/
  cmc_small/
  cmc_tini/
```
