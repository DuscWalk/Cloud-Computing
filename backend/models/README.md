# 固定模型版本

来源：OpenCV Zoo commit `47534e27c9851bb1128ccc0102f1145e27f23f98`。

| 模型 | SHA-256 | 许可 |
| --- | --- | --- |
| face_detection_yunet_2023mar.onnx | 8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4 | MIT，见 YUNET-LICENSE |
| face_recognition_sface_2021dec.onnx | 0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79 | Apache 2.0，见 SFACE-LICENSE |

在 backend 目录运行 `uv run python -m app.model_assets` 下载并校验。权重不进入 Git，Worker 启动时再次校验，绝不在线自动回退至 FRS。CPU 后端为 OpenCV DNN 4.11.0，默认 2 个 OpenCV 线程。

初始余弦阈值 0.50、第二候选差距 0.08 是保守起点，需通过参加课程验收的真实照片校准。公开测试图片只能验证流程，不能据此声称实测准确率或活体检测能力。
