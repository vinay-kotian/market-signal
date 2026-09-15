class LoginError(ValueError):
    """Only fixed, credential-free messages may be sent to the frontend."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def describe(error):
    if isinstance(error, LoginError):
        return {'code': error.code, 'message': str(error)}
    return {'code': 'LOGIN_FAILED', 'message': 'Login failed unexpectedly. Start a fresh login and check the backend configuration.'}
