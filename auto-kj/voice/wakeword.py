import numpy as np
from openwakeword.model import Model


class WakeWordListener:
    def __init__(self, model_name: str = "hey_jarvis", threshold: float = 0.5):
        self.model = Model()
        self.model_name = model_name
        self.threshold = threshold

    def process_frame(self, frame: np.ndarray) -> bool:
        prediction = self.model.predict(frame)
        score = max(prediction.values()) if prediction else 0
        return score >= self.threshold

    def reset(self):
        self.model.reset()
