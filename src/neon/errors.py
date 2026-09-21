from .position import Position


class NeonError(Exception):
    """Error of the scanner, the parser, the evaluation of values, the encoder or an edit."""

    def __init__(self, message: str, position: Position | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position

    def __str__(self) -> str:
        if self.position:
            return f"{self.message} on line {self.position.line} at column {self.position.column}"
        return self.message
