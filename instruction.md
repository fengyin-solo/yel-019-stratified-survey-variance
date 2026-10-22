# 分区抽样均值的复核

年度客户回访刚封样，运营需要给管理层一个总体满意度均值。样本按客户规模分了层，各层抽样比例不同，直接把所有答卷平均会偏向样本较多的层；复核组还要求同时给出计入有限总体修正的标准误和置信区间。请修正 `/app/stratified_survey_variance.py`，把它接到现有回访导出流程里。

## 回访文件

原始回访导出按 UTF-8 文本送入程序。外层对象没有清单外字段。

```text
survey_id
confidence_level
strata
```

`survey_id` 由两至四十八个字符组成；编号不能以空白包住，也不可在内部夹控制字符。`confidence_level` 是 0.8 到 0.999 的有限数。`strata` 是 2 到 12 个分层，每一层由三个指定字段构成：

```text
stratum_id
population
responses
```

层编号匹配 `[A-Z][A-Z0-9_-]{0,23}` 且不重复；`population` 是 2 到 1000000000 的整数；`responses` 是 2 到 500 个有限数值，数量不得超过该层人口数。布尔值不能当整数或小数。

复核工具从命令行接收两个位置参数；文件位置不靠环境变量传递。

```bash
python3 /app/stratified_survey_variance.py <回访文件> <复核结果>
```

## 统计口径

记第 h 层人口为 `N_h`，样本量为 `n_h`，样本均值为 `m_h`，样本方差为：

```text
s_h^2 = sum((x - m_h)^2) / (n_h - 1)
```

总体样本量是 `N = sum(N_h)`。总体均值的分层估计为 `sum(N_h/N * m_h)`。其方差估计为：

```text
sum((N_h/N)^2 * (1 - n_h/N_h) * s_h^2 / n_h)
```

标准误是该方差的正平方根。置信区间以估计值为中心，半宽为 `z * 标准误`，其中 `z` 是标准正态分布双侧区间的分位数，例如 0.95 对应约 1.959963984540054。某层已经全查时，该层的有限总体修正因子为 0。

## 复核结果

复核单的排版必须紧凑，并以一个 LF 收尾。顶层键顺序为：

```text
survey_id
status
estimate
standard_error
ci_low
ci_high
strata
```

`status` 写 `complete`。各层结果沿用回访单中的层序。每个层结果固定保留五个字段：

```text
stratum_id
sample_size
population
mean
variance_contribution
```

最后一栏是该层对总体均值方差的贡献，不是标准误。所有统计量保留 Python 双精度计算结果，不额外舍入。

程序成功时标准输出和标准错误都不写内容。拿同一份回访材料重跑复核，统计单应保持相同字节。输出先落同目录暂存项后替换；失败不破坏旧结果，暂存项会被清除。

## 退回

回访材料只要无法按上述 schema 读取，命令就以 1 结束。标准错误只写 `运行拒收: BAD_INPUT`。

复核单所在目录不能写、目标已被目录占用或路径失效时，退出码为 1，原文件不动且标准错误写 `运行拒收: IO_FAILURE`。

被拒收的回访批次不应向终端抛出 `traceback`。
