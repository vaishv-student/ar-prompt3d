/**
 * Thin wrapper around the Web Speech API's SpeechRecognition, with
 * feature detection since it isn't universally supported (e.g. Firefox).
 */

const SpeechRecognitionImpl =
  window.SpeechRecognition || window.webkitSpeechRecognition || null;

export function isVoiceSupported() {
  return SpeechRecognitionImpl !== null;
}

export function createVoiceInput({ onResult, onStart, onEnd, onError }) {
  if (!SpeechRecognitionImpl) return null;
  const recognition = new SpeechRecognitionImpl();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => onStart && onStart();
  recognition.onend = () => onEnd && onEnd();
  recognition.onerror = (e) => onError && onError(e.error);
  recognition.onresult = (e) => {
    const transcript = e.results[0][0].transcript;
    onResult && onResult(transcript);
  };

  return recognition;
}
