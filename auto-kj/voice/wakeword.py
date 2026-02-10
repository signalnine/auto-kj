import os
import numpy as np
from openwakeword.model import Model


class WakeWordListener:
    def __init__(self, model_path: str = None, threshold: float = 0.5):
        if model_path and os.path.exists(model_path):
            self.model = Model(wakeword_models=[model_path], inference_framework="onnx")
        else:
            self.model = Model(inference_framework="onnx")
        self.threshold = threshold

    def process_frame(self, frame: np.ndarray) -> bool:
        prediction = self.model.predict(frame)
        score = max(prediction.values()) if prediction else 0
        return score >= self.threshold

    def reset(self):
        self.model.reset()
