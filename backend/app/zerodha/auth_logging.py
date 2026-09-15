import logging


class CallbackTokenFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn's access record args: client, method, path+query, version, status.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str) and '/zerodha/callback' in args[2]:
                args[2] = args[2].split('?', 1)[0]
                record.args = tuple(args)
        return True


def redact_callback_logs():
    logger = logging.getLogger('uvicorn.access')
    if not any(isinstance(item, CallbackTokenFilter) for item in logger.filters):
        logger.addFilter(CallbackTokenFilter())
