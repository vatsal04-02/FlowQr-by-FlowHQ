"""WhatsApp automation (official Meta Cloud API). See docs/WHATSAPP_AUTOMATION.md."""


class WaError(Exception):
    """A refusal with a plain-words message for the screen and a stable code for the code."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message}
