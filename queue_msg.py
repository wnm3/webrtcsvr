# generic imports
import copy
import json
from threading import RLock

# prx imports
from constants import constants as CONST


class queue_msg(object):
    """Prioritized event message for sending through priority_msg_queue"""

    # static variables
    MSG_CLASS_SYSTEM = 0
    MSG_CLASS_USER = 1
    MSG_CLASS_ASSISTANT = 2
    MSG_CLASS_AUDIO_WAV = 3
    MSG_TYPE_SHUTDOWN = "shutdown"
    MSG_SEQ = 1000000  # large enough not to overlap with wav data sequence numbers
    LOCK = RLock()

    def __init__(self, priority_class: int, event: dict | str, seq: int = -1):
        """Constructor for a prioritized event message

        Args:
            priority_class (int): the priority (system=0, user=1, assistant=2, audio_wav=3)
            event (dict | str): the event or string (to signal stopping)
            seq (int|None): a sequence value used for sorting entries in the queue (None will generate a value > 1000000)
        """
        if isinstance(event, str):
            event = {"type": event}
        self.priority_class = priority_class
        if seq == -1:
            with queue_msg.LOCK:
                queue_msg.MSG_SEQ += 1
                self.seq = queue_msg.MSG_SEQ
        else:
            self.seq = seq
        # This protects against an event that is
        # published to the queue being modified before consumption
        self.event = copy.deepcopy(event)

    def __json__(self):
        return f'{{ "{CONST.EVENT}": {json.dumps(self.get_event())}, "{CONST.PRIORITY_CLASS}": "{self.get_priority_class()}", "{CONST.SEQ}": {self.get_seq()} }}'

    def __lt__(self, other: "queue_msg"):
        """Compares this event with the other event and returns True if this is less than the other

        Args:
            other (queue_msg): True if this is less than the other

        Returns:
            _type_: _description_
        """
        pri_diff = self.priority_class - other.priority_class
        if pri_diff == 0:
            return self.seq < other.seq
        return pri_diff < 0

    def get_event(self) -> dict:
        """Returns the event in this message

        Returns:
            dict: the event in this message
        """
        return self.event

    def get_priority_class(self) -> int:
        """Returns the priority class of the message (system=0, user=1, assistant=2)

        Returns:
            int: the priority class of the message (system=0, user=1, assistant=2)
        """
        return self.priority_class

    def get_seq(self) -> int:
        """Returns the sequential index of this message (to break ties, larger is newer)

        Returns:
            int: the sequential index of this message (to break ties, larger is newer)
        """
        return self.seq

    def is_assistant(self) -> bool:
        """Returns True if this is an assistant priority (2) message

        Returns:
            bool: True if this is an assistant priority (2) message
        """
        return self.priority_class == queue_msg.MSG_CLASS_ASSISTANT

    def is_system(self) -> bool:
        """Returns True if this is a system priority (0) message

        Returns:
            bool: True if this is a system priority (0) message
        """
        return self.priority_class == queue_msg.MSG_CLASS_SYSTEM

    def is_user(self) -> bool:
        """Returns True if this is a user priority (1) message

        Returns:
            bool: True if this is a user priority (1) message
        """
        return self.priority_class == queue_msg.MSG_CLASS_USER

    @staticmethod
    def make_assistant_msg(event: dict | str) -> "queue_msg":
        """Create an assistant priority (2) message

        Args:
            event (dict | str): the event or string (to signal stopping)

        Returns:
            queue_msg: prioritized event message
        """
        if isinstance(event, str):
            event = {"type": event}
        return queue_msg(queue_msg.MSG_CLASS_ASSISTANT, event)

    @staticmethod
    def make_audio_playback_shutdown_msg() -> "queue_msg":
        """Create a shutdown system priority (0) message

        Returns:
            queue_msg: prioritized event message
        """
        event = {CONST.TYPE: queue_msg.MSG_TYPE_SHUTDOWN}
        return queue_msg(queue_msg.MSG_CLASS_SYSTEM, event)

    @staticmethod
    def make_audio_wav_msg(event: dict | str, seq: int = -1) -> "queue_msg":
        """Create a system priority (0) message

        Args:
            event (dict | str): the event or string (to signal stopping)

        Returns:
            queue_msg: prioritized event message
        """
        if isinstance(event, str):
            event = {CONST.TYPE: event}
        else:
            evtype = event.get(CONST.TYPE, None)
            if evtype is None:
                event[CONST.TYPE] = queue_msg.MSG_CLASS_AUDIO_WAV
        return queue_msg(queue_msg.MSG_CLASS_SYSTEM, event, seq)

    @staticmethod
    def make_system_msg(event: dict | str) -> "queue_msg":
        """Create a system priority (0) message

        Args:
            event (dict | str): the event or string (to signal stopping)

        Returns:
            queue_msg: prioritized event message
        """
        if isinstance(event, str):
            event = {"type": event}
        return queue_msg(queue_msg.MSG_CLASS_SYSTEM, event)

    @staticmethod
    def make_user_msg(event: dict | str) -> "queue_msg":
        """Create a user priority (1) message

        Args:
            event (dict | str): the event or string (to signal stopping)

        Returns:
            queue_msg: prioritized event message
        """
        if isinstance(event, str):
            event = {"type": event}
        return queue_msg(queue_msg.MSG_CLASS_USER, event)
