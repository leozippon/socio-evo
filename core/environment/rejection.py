"""The signal that reality cannot honour an action."""


class Rejected(Exception):
    """An action that reality cannot honour; the message is the reason shown to the actor.

    Raised before anything changes, so a rejected action leaves reality as it was.
    """
