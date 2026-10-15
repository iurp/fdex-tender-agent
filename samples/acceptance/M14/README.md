# M14 专项测试操作卡

任务：[M14] 实际位置与证据审查；范围：将trace对应到实际Word表格单元格和附件关系，检测伪造或错位映射。

## 输入与预期

每个用例的 input.json 只描述输入，case.json 列实际原件路径与SHA256；expected.json 是供测试对比的公开预期，禁止作为运行输入。

| 用例 | 类型 | 目的 | 预期状态 |
|---|---|---|---|
| [normal](normal/case.json) | normal | 表格单元格与实际图片关系都正确 | COMPLETE |
| [review](review/case.json) | review | 没有trace不能声称位置都已检查 | REVIEW |
| [abnormal](abnormal/case.json) | abnormal | trace指错单元格但Word本身正常 | BLOCKED |
| [change](change/case.json) | change | 实际DOCX注入 swap-images | BLOCKED |
| [missing-image](missing-image/case.json) | abnormal | 实际DOCX注入 missing-image | BLOCKED |
| [wrong-project](wrong-project/case.json) | abnormal | 实际DOCX注入 wrong-project | BLOCKED |
| [old-person](old-person/case.json) | abnormal | 实际DOCX注入 old-person | BLOCKED |
| [placeholder](placeholder/case.json) | abnormal | 实际DOCX注入 placeholder | BLOCKED |

## 直接执行

先验证自己拿到的是完整数据包：

```bash
python tools/task_acceptance.py verify-kit --module M14
```

开发适配器读取 input.json，调用自己的模块并输出 result.json；结果投影与适配器接口见 docs/testing.md。不需要改生产接口或安装新服务。

```bash
python tools/task_acceptance.py run --module M14 --adapter adapters/m14.py --output outputs/m14-test-01
```

没有实现适配器时命令会明确失败，不能把verify-kit通过当成功能通过。正常/需复核/异常分支都由检查器判定，不以进程退出0代替业务结果。

已有实际输出也可单例检查：

```bash
python tools/task_acceptance.py check --module M14 --case normal --result outputs/my-run/result.json
```

## PR 必交

运行命令、整套report.json、正常与异常实际输出、新增回归测试、至少一次实际上游文件联调、接口影响和未完成范围。Word任务还交实际DOCX及逐页视觉检查；OCR交像素区域证据和引擎/模型执行记录。

固定输入通过不保证泛化：复审会改变项目、人物、数值或文件顺序。不得复制参考预期冒充实现。代码合并不是业务批准。
