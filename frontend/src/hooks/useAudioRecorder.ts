import { useCallback, useMemo, useRef, useState } from 'react'

type RecorderState = 'idle' | 'recording' | 'ready'

const PICKED_MIME_TYPES = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4']

const getSupportedMimeType = () => {
  if (typeof MediaRecorder === 'undefined') {
    return ''
  }
  const found = PICKED_MIME_TYPES.find((type) => MediaRecorder.isTypeSupported(type))
  return found ?? ''
}

export function useAudioRecorder() {
  const [state, setState] = useState<RecorderState>('idle')
  const [error, setError] = useState<string | null>(null)
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<BlobPart[]>([])

  const isSupported =
    typeof window !== 'undefined' &&
    typeof MediaRecorder !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  const isRecording = state === 'recording'
  const hasRecording = !!audioBlob
  const mimeType = useMemo(getSupportedMimeType, [])

  const start = useCallback(async () => {
    if (!isSupported) {
      setError('Audio recording is not supported in this browser.')
      return
    }

    try {
      setError(null)
      setAudioBlob(null)
      chunksRef.current = []

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream)

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const blobType = mimeType || 'audio/webm'
        const blob = new Blob(chunksRef.current, { type: blobType })
        setAudioBlob(blob)
        setState('ready')
        chunksRef.current = []

        stream.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }

      streamRef.current = stream
      mediaRecorderRef.current = recorder
      recorder.start()
      setState('recording')
    } catch {
      setError('Microphone access was denied or unavailable.')
      setState('idle')
    }
  }, [isSupported, mimeType])

  const stop = useCallback(() => {
    const recorder = mediaRecorderRef.current
    if (!recorder || recorder.state !== 'recording') {
      return
    }
    recorder.stop()
    mediaRecorderRef.current = null
  }, [])

  const clear = useCallback(() => {
    setAudioBlob(null)
    setError(null)
    setState('idle')
  }, [])

  return {
    isSupported,
    isRecording,
    hasRecording,
    audioBlob,
    error,
    clearError: () => setError(null),
    start,
    stop,
    clear
  }
}
