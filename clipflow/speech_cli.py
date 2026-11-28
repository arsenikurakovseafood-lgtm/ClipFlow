"""Decode an extracted mono WAV in a short-lived cloud worker process."""
import json
import sys
import wave


def recognize(model_path, audio_path):
    from vosk import KaldiRecognizer, Model, SetLogLevel

    SetLogLevel(-1)
    recognizer = KaldiRecognizer(Model(model_path), 16000)
    recognizer.SetWords(True)
    words = []
    with wave.open(audio_path, 'rb') as audio:
        while chunk := audio.readframes(4000):
            if recognizer.AcceptWaveform(chunk):
                words.extend(json.loads(recognizer.Result()).get('result', []))
    words.extend(json.loads(recognizer.FinalResult()).get('result', []))
    return words


if __name__ == '__main__':
    print(json.dumps(recognize(*sys.argv[1:])))
