"""The signal that reality cannot honour an action."""


class Rejected(Exception):
    """An action that reality cannot honour; the message, a sentence told as the resident
    meets it, is what the actor is told.

    Raised before anything changes, so a rejected action leaves reality as it was.
    """


class AssessmentUnavailable(Exception):
    """Infrastructure could not produce a verdict; never evidence of poor work."""
