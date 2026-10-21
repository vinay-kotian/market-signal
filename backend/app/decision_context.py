"""Additive explanation metadata; exception messages and rejection rules stay unchanged."""
class DecisionRejection(ValueError):
    def __init__(self, reason, context):
        super().__init__(reason)
        self.context = context
