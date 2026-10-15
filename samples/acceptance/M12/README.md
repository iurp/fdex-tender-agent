# M12 专项测试操作卡

任务：[M12] 确定性报价计算；范围：用Decimal实现3组数量/单价/税费/舍入明确的计算与超限检测。

## 输入与预期

每个用例的 input.json 只描述输入，case.json 列实际原件路径与SHA256；expected.json 是供测试对比的公开预期，禁止作为运行输入。

| 用例 | 类型 | 目的 | 预期状态 |
|---|---|---|---|
| [normal](normal/case.json) | normal | 三个独立报价与半分舍入 | COMPLETE |
| [review](review/case.json) | review | 缺税费口径不能默认零税 | REVIEW |
| [abnormal](abnormal/case.json) | abnormal | 超限与总价不一致同时报告 | BLOCKED |
| [change](change/case.json) | change | 单价变化不能继承旧报价批准 | REVIEW |

## 直接执行

先验证自己拿到的是完整数据包：

```bash
python tools/task_acceptance.py verify-kit --module M12
```

开发适配器读取 input.json，调用自己的模块并输出 result.json；结果投影与适配器接口见 docs/testing.md。不需要改生产接口或安装新服务。

```bash
python tools/task_acceptance.py run --module M12 --adapter adapters/m12.py --output outputs/m12-test-01
```

没有实现适配器时命令会明确失败，不能把verify-kit通过当成功能通过。正常/需复核/异常分支都由检查器判定，不以进程退出0代替业务结果。

已有实际输出也可单例检查：

```bash
python tools/task_acceptance.py check --module M12 --case normal --result outputs/my-run/result.json
```

## PR 必交

运行命令、整套report.json、正常与异常实际输出、新增回归测试、至少一次实际上游文件联调、接口影响和未完成范围。Word任务还交实际DOCX及逐页视觉检查；OCR交像素区域证据和引擎/模型执行记录。

固定输入通过不保证泛化：复审会改变项目、人物、数值或文件顺序。不得复制参考预期冒充实现。代码合并不是业务批准。
