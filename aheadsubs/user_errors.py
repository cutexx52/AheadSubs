"""Actionable application errors with stable keys for localized desktop clients."""


class UserInputError(ValueError):
    def __init__(self, code, message, *display_args):
        super().__init__(message)
        self.code = code
        self.display_args = display_args


class ServiceStateError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
