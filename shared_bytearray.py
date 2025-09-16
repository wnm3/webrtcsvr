import threading


class shared_bytearray:
    """Class that handles synchronized access to the same bytearray for sharing across threads (e.g, using a writer and a reader)"""

    def __init__(self):
        """Constructor for shared_bytearray"""
        self.tlock = threading.Lock()
        self.byte_array = bytearray()

    def clear(self):
        """Clears the content of this shared_bytearray"""
        with self.tlock:
            self.byte_array.clear()

    def get_bytes(self) -> list:
        with self.tlock:
            return list(self.byte_array)

    def extend(self, chunk: bytearray | bytes):
        """Adds the supplied bytearray content or bytes to the end of this shared_bytearray

        Args:
            chunk (bytearray | bytes): the data to be added
        """
        with self.tlock:
            self.byte_array.extend(chunk)

    def extract(self, chunk_size: int) -> bytearray:
        """Removes a chunk_size bytearray of data from the start of this shared_bytearray, or returns an empty bytearray if not enough data is available.

        Args:
            chunk_size (int): the number of bytes to be returned in a bytearray, and removed from this shared_bytearray

        Returns:
            bytearray: the bytearray removed from the beginning of this bytearray, or an empty bytearray if not enough data is available
        """
        chunk = bytearray()
        with self.tlock:
            if len(self.byte_array) >= chunk_size:
                chunk = self.byte_array[0:chunk_size]
                del self.byte_array[0:chunk_size]
        return chunk

    def __len__(self) -> int:
        """Dunder method for length calculations

        Returns: the number of bytes currently stored in this shared_bytearray
            int: _description_
        """
        with self.tlock:
            return len(self.byte_array)
