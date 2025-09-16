import traceback
import numpy as np
import torch
import torchaudio
from numpy import ndarray as NDArray


@staticmethod
def int2float(sound: NDArray | list[int]) -> NDArray:
    """Convert the sound

    Args:
        sound (NDArray): array of int16 sound values

    Returns:
        NDArray: sound as float32 sound values between [-1.0,1.0]
    """
    if type(sound) is not NDArray:
        sound = np.array(sound)
    return sound.astype(np.float32) / 32768.0


def audio_to_tensor(audio_frame: bytes) -> torch.Tensor:
    """Converts the audio bytes to a torch Tensor

    Args:
        audio_frame (bytes): input audio int16 frame

    Returns:
        torch.Tensor: the tensor of 32-bit float values
    """
    buffer = int2float(np.frombuffer(audio_frame, dtype=np.int16))
    return torch.from_numpy(buffer)


try:
    print("Enter the timestamp or q to quit: ")
    timestamp = input()
    if "q" == timestamp.lower():
        exit()

    print(
        "Enter sample rate (e.g., 24000, nothing uses defaults for file types), or q to quit"
    )
    sample_rate_str = input()
    if "q" == sample_rate_str.lower():
        exit()
    if not sample_rate_str:
        sample_rate_str = "Auto"

    input_filestems = [
        "tmp_01_rawaudio_24_",
        "tmp_02_monoframe_24_",
        "tmp_03_stereoframe_48_",
        "tmp_04_sendframe_48_",
    ]
    input_samplerates = [
        24000,
        24000,
        48000,
        48000,
    ]
    index = -1
    for filestem in input_filestems:
        index += 1
        input_filename = filestem + timestamp
        try:
            with open(input_filename, "rb") as file:
                voice_data = file.read()
                voice_tensor = audio_to_tensor(bytes(voice_data))
                if voice_tensor.shape[0] > 1:
                    voice_tensor = voice_tensor.reshape(1, len(voice_tensor))

                ## saving as a wav file ##
                voice_tensor = voice_tensor.cpu()
                stt_logfilename = input_filename + ".wav"
                if sample_rate_str == "Auto":
                    sample_rate = input_samplerates[index]
                else:
                    sample_rate = int(sample_rate_str)

                torchaudio.save(stt_logfilename, voice_tensor, sample_rate=sample_rate)
                print(f"Saved wav file as {stt_logfilename}")
        except Exception as e:
            print(f"Skipping {input_filename} due to error {e}")
except Exception:
    traceback.print_exc()
