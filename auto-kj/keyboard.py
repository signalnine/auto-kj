import logging
import threading

log = logging.getLogger(__name__)

try:
    from evdev import InputDevice, ecodes, list_devices
    KEY_MAP = {
        ecodes.KEY_SPACE: "space",
        ecodes.KEY_ESC: "escape",
        ecodes.KEY_UP: "up",
        ecodes.KEY_DOWN: "down",
        ecodes.KEY_Q: "q",
    }
    HAS_EVDEV = True
except (ImportError, AttributeError):
    HAS_EVDEV = False
    KEY_MAP = {}


class KeyboardHandler:
    def __init__(self):
        self._callbacks: dict[str, callable] = {}

    def on(self, key_name: str, callback: callable):
        self._callbacks[key_name] = callback

    def dispatch(self, key_name: str):
        cb = self._callbacks.get(key_name)
        if cb:
            cb()

    def start(self, device_path: str | None = None):
        if not HAS_EVDEV:
            log.warning("evdev not available — keyboard controls disabled")
            return
        if device_path is None:
            device_path = self._find_keyboard()
        if device_path is None:
            log.warning("No keyboard device found — keyboard controls disabled")
            return
        thread = threading.Thread(
            target=self._listen, args=(device_path,), daemon=True
        )
        thread.start()

    def _find_keyboard(self) -> str | None:
        for path in list_devices():
            dev = InputDevice(path)
            caps = dev.capabilities()
            if ecodes.EV_KEY in caps:
                keys = caps[ecodes.EV_KEY]
                if ecodes.KEY_SPACE in keys and ecodes.KEY_ESC in keys:
                    return path
        return None

    def _listen(self, device_path: str):
        dev = InputDevice(device_path)
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.value == 1:  # key down
                key_name = KEY_MAP.get(event.code)
                if key_name:
                    self.dispatch(key_name)
