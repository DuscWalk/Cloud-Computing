# 公共测试图片来源

仅用于真实模型的可重复集成测试，不代表课堂人员数据集，也不用于训练。

- `astronaut.png`：NASA 宇航员 Eileen Collins 公开肖像（美国政府作品、公有领域），取自 scikit-image v0.25.2 `skimage/data/astronaut.png`。SHA-256：`88431cd9653ccd539741b555fb0a46b61558b301d4110412b5bc28b5e3ea6cb5`。
- `grace_hopper.jpg`：美国海军 Grace Hopper 公开肖像（美国政府作品、公有领域），取自 Matplotlib v3.10.1 `lib/matplotlib/mpl-data/sample_data/grace_hopper.jpg`。SHA-256：`a8ca6d734765703b09728ab47fe59f473d93ae3967fc24c7c0288c3c7adb7130`。

测试将同一肖像的轻微旋转/亮度变化用于已录入匹配，将另一位人物用于未录入拒识，将拼接图用于多脸拒绝。必须另行采集经同意的真实手机照片完成阈值校准和课程验收。
